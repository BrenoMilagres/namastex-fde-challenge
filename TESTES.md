# Casos de uso para teste (curl)

Roteiro pra exercitar o agente de ponta a ponta pelo webhook. Cada cenário tem o
comando `curl`, o que esperar na resposta e qual evento aparece no
`agent/logs/trace.jsonl`.

## Pré-requisitos

```bash
# 1. Subir o stack (quote-api + postgres + agent) com a chave do Gemini no .env
docker compose up -d

# 2. Conferir que o agente está no ar
curl -s http://localhost:8080/health          # -> {"status":"ok"}
```

O webhook é `POST http://localhost:8080/webhook` com corpo
`{"conversation_id": "...", "message": "..."}` e responde
`{"conversation_id", "reply", "handed_off"}`.

> **Quota do Gemini:** o free tier do `gemini-2.5-flash` tem ~20 requisições/dia.
> Cada turno gasta 1 chamada (2 quando o agente cota — uma pra decidir cotar, outra
> pra formatar). Se estourar (`429 RESOURCE_EXHAUSTED`), o agente **não quebra**: o
> webhook loga o erro (com stacktrace), registra `handoff: erro_interno` no trace e
> responde `HTTP 200` com uma mensagem amigável de transferência (`handed_off: true`)
> — é a cota, não um bug. A cota reseta no dia seguinte; ou troque o modelo em
> `AGENT_MODEL` (ex.: `gemini-2.5-flash-lite`, com mais cota) e reinicie o agente.

> Os comandos abaixo são para **bash/WSL**. O estado de cada conversa é persistido
> por `conversation_id` (checkpointer no Postgres), então mensagens com o mesmo id
> continuam a mesma conversa.

## Controles úteis

```bash
# Ver o trace ao vivo (num terminal separado)
tail -f agent/logs/trace.jsonl | jq

# Zerar o estado das conversas (recomeçar do zero)
docker compose exec -T postgres psql -U agent -d langgraph \
  -c "TRUNCATE checkpoints, checkpoint_blobs, checkpoint_writes;"

# Forçar a /quote a se comportar de um jeito específico (reinicia só o mock):
QUOTE_FAILURE_RATE=0    docker compose up -d quote-api   # sempre estável
QUOTE_FAILURE_RATE=1    docker compose up -d quote-api   # sempre fora do ar (5xx)
QUOTE_FAILURE_RATE=0.20 docker compose up -d quote-api   # volta ao default instável
```

## Vendo os logs do agente

O `trace.jsonl` mostra o *fluxo de negócio* (mensagens, cotações, handoff). Já os
**logs do container** mostram o que rolou por baixo — erros, stacktrace, chamadas ao
modelo. É onde olhar quando uma resposta vier estranha ou cair em `erro_interno`.

```bash
# Últimas linhas
docker compose logs agent

# Acompanhar ao vivo
docker compose logs -f agent

# Só o que aconteceu nos últimos 2 minutos
docker compose logs agent --since 2m

# Filtrar erros/falhas (ex.: exceção tratada na borda do webhook, 429 de cota)
docker compose logs agent --since 5m | grep -iE "falha ao processar|error|traceback|429|resource_exhausted"
```

Exemplo: quando a cota do Gemini estoura, o webhook responde amigável
(`handoff: erro_interno` no trace) e o **motivo real** — o `429 RESOURCE_EXHAUSTED`
com stacktrace — fica aqui no log do container.

---

## 1. Caminho feliz — cotação OK

Lead com todos os dados; escolhe o plano e recebe o preço. **Requer a API estável**
(`QUOTE_FAILURE_RATE=0`), senão uma falha transitória pode cair no cenário 2.

```bash
QUOTE_FAILURE_RATE=0 docker compose up -d quote-api

curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t1","message":"oi quero seguro, tenho 40 anos, gol 2019, cep 20090-003. meu cpf e 123.456.789-00, email joao@gmail.com, tel 21 99888-7654"}'

curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t1","message":"quero o plano completo"}'
```

**Esperado:** o agente pergunta o plano, depois retorna o **prêmio mensal** (ex.:
`R$ 241,38`), coberturas e o aviso de **carência de 30 dias**. `handed_off: false`.
No trace: `message` (PII **mascarada** — CPF/e-mail/telefone), um `quote` com
`outcome: ok`, e a resposta final.

---

## 2. API fora do ar — nunca inventa preço

`/quote` falhando em todas as tentativas. **Requer `QUOTE_FAILURE_RATE=1`.**

```bash
QUOTE_FAILURE_RATE=1 docker compose up -d quote-api

curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t2","message":"boa tarde, seguro pro meu Onix 2021, tenho 33 anos, cep 30140-071"}'

curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t2","message":"pode ser o premium"}'
```

**Esperado:** o agente avisa com transparência que o sistema está indisponível e que
um humano vai concluir — **sem nenhum preço**. `handed_off: true`. No trace: um
`quote` com `outcome: indisponivel` e 3 `attempts` (5xx), seguido de
`handoff: api_indisponivel`.

> Ao terminar, volte a API pro default: `QUOTE_FAILURE_RATE=0.20 docker compose up -d quote-api`

---

## 3. Cotação recusada — perfil fora da alçada

Idade acima do limite (75 anos) → a API responde `422`. **Requer API estável**
(`QUOTE_FAILURE_RATE=0`) pra não cair no cenário 2 antes do 422.

```bash
QUOTE_FAILURE_RATE=0 docker compose up -d quote-api

curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t3","message":"quero cotar, tenho 80 anos, meu carro e um Civic 2023, cep 04567-000"}'

curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t3","message":"quero o completo"}'
```

**Esperado:** o agente explica com empatia que esse perfil precisa de análise humana e
transfere. `handed_off: true`. No trace: `quote` com `outcome: recusada` (motivo:
idade acima do limite) e `handoff: cotacao_recusada`.

---

## 4. Lead pede atendente humano

```bash
curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t4","message":"nao quero falar com robo, me passa pra um atendente humano de verdade"}'
```

**Esperado:** o agente avisa que vai transferir. `handed_off: true`. No trace:
`handoff: lead_pediu_humano`. O marcador interno `[HANDOFF:humano]` **não** aparece
na resposta ao lead (é removido antes de enviar).

---

## 5. Fora de escopo

Assunto que não é seguro auto (ex.: plano de saúde).

```bash
curl -s -X POST http://localhost:8080/webhook -H "Content-Type: application/json" \
  -d '{"conversation_id":"t5","message":"na verdade eu queria contratar um plano de saude pra minha familia, voces vendem isso?"}'
```

**Esperado:** o agente diz que a AutoSeguro é focada em seguro auto e transfere.
`handed_off: true`. No trace: `handoff: fora_de_escopo` (marcador `[HANDOFF:escopo]`
também removido da resposta).

---

## Conferindo o resultado

```bash
# Resumo por tipo de evento e motivos de handoff
docker compose exec -T agent sh -c "cat logs/trace.jsonl" | \
  jq -c 'select(.type=="handoff") | {conversation_id, reason}'
```

Os quatro motivos de handoff (`api_indisponivel`, `cotacao_recusada`,
`lead_pediu_humano`, `fora_de_escopo`) devem aparecer, um por cenário.
