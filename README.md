# AutoSeguro — Agente de Vendas (Desafio FDE / Namastex)

Agente de vendas de seguro auto que atende um lead de ponta a ponta pelo estilo
WhatsApp (português): **conversa → qualifica → cota → decide** (resolve sozinho ou
passa pra um humano). O foco de engenharia está em **não quebrar nem inventar preço
quando a API de cotação falha** — que é o ponto mais pesado da avaliação.

> O enunciado original do desafio está em [DESAFIO.md](DESAFIO.md).

O que a solução entrega, em uma olhada:

- **Orquestração com LangGraph** (grafo de estados explícito) + **Gemini** (via LangChain).
- **Cliente resiliente da `/quote`**: timeout curto, retry com backoff só em falha transitória, e **nunca fabrica preço** — falha vira handoff.
- **Handoff explícito**, com gatilhos enumerados em código.
- **Rastreabilidade** por trace JSONL (uma linha por mensagem/cotação/handoff, com status e latência).
- **PII mascarada** antes de qualquer log — e antes de indexar o dataset.
- **Memória durável** da conversa no Postgres (checkpointer do LangGraph).
- **Few-shot** com as conversas que converteram, via busca vetorial (pgvector).
- **Sobe tudo com Docker** (`docker compose up`).

---

## Como rodar (Docker)

Pré-requisitos: Docker e uma **chave do Google AI Studio (Gemini)**

**Gerando a chave (grátis, uma vez):**

1. Acesse [aistudio.google.com/apikey](https://aistudio.google.com/apikey) e entre com uma conta Google.
2. Clique em **Create API key** e copie a chave.
3. Não precisa de cartão nem billing — o tier gratuito do Gemini cobre esta demo.

```bash
# 1. chave na raiz (o docker-compose le este .env sozinho)
cp .env.example .env        # e cole a sua GOOGLE_API_KEY

# 2. sobe quote-api (instavel de proposito) + postgres + agent
docker compose up -d

# 3. indexa o historico no pgvector -> habilita o few-shot (1x, ~1min; idempotente)
docker compose --profile index run --rm indexer

# 4. conversa com o agente
curl -s -X POST localhost:8080/webhook -H 'content-type: application/json' \
  -d '{"conversation_id":"c1","message":"oi, quero seguro pro meu Corolla 2022, tenho 35 anos, cep 01310-100"}'
```

Resposta: `{ "conversation_id": "c1", "reply": "...", "handed_off": false }`. O
`conversation_id` mantém a conversa (estado no Postgres) — mande várias mensagens
com o mesmo id pra qualificar, escolher plano e cotar.

O passo 3 é executado uma vez (o índice fica no volume do Postgres e sobrevive a
restarts; rodar de novo apenas confirma e pula). Se você pular esse passo, o agente
**funciona igual** — só sem os exemplos de few-shot, que degradam graciosamente.

Pra **forçar** a reconstrução do índice (ex.: mudou o dataset), passe `-e REINDEX=1`
**antes** do nome do serviço:

```bash
docker compose --profile index run --rm -e REINDEX=1 indexer
```

**Trace da execução:** cada passo é gravado em `agent/logs/trace.jsonl` (ver
[Rastreabilidade](#rastreabilidade) e [Log de execução](#log-de-execução)).

<details>
<summary>Rodar no host (dev, sem Docker do agente)</summary>

```bash
cp .env.example .env                         # na raiz; cole a GOOGLE_API_KEY
docker compose up -d quote-api postgres      # dependencias
cd agent && uv sync
uv run uvicorn app.main:app --env-file ../.env --port 8080
```
As URLs padrão do `.env` já apontam pro `localhost` (modo host). No Docker, o
compose sobrescreve com os nomes de serviço.
</details>

---

## Arquitetura

```
   lead (WhatsApp) ──POST /webhook──►  Agente (FastAPI + LangGraph)
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                      ▼
              quote-service         Postgres (pgvector)     trace.jsonl
              (POST /quote,       checkpointer da conversa   (auditoria)
               instavel)          + indice de few-shot
```

**O grafo do agente** ([agent/app/agent.py](agent/app/agent.py)):

```
START → model ──(tool_use?)──► quote ──► model      (loop de cotação)
             └──(texto)──────► respond ──(handoff?)──► handoff → END
                                     └──────────────────────► END
```

- **model** — chama o Gemini com a tool `cotar`; injeta few-shot no system prompt.
- **quote** — executa o cliente resiliente da `/quote`, registra o trace e detecta handoff.
- **respond** — extrai a resposta, decide se houve handoff.
- **handoff** — `interrupt()` do LangGraph (human-in-the-loop): pausa pra um humano assumir.

Módulos (em `agent/app/`):

| Arquivo | Papel |
|---|---|
| `quote_client.py` | Cliente resiliente da `/quote` (retry/timeout, nunca inventa preço) |
| `handoff.py` | Política de handoff (gatilhos enumerados) |
| `tracing.py` | Trace estruturado JSONL (PII mascarada) |
| `pii.py` | Masking de CPF/e-mail/telefone/placa; extração de CEP |
| `tools.py` | Schema da tool `cotar` + system prompt |
| `agent.py` | Grafo LangGraph + few-shot |
| `retrieval.py` | Busca vetorial (pgvector) das conversas do histórico |
| `main.py` | Webhook FastAPI (`/webhook`, `/health`) |

---

## Decisões (e por quê)

### Resiliência da `/quote` — o ponto central
Em [quote_client.py](agent/app/quote_client.py), a regra de ouro é **nunca inventar
um preço**. A política:

- **Timeout curto por tentativa** (5s, configurável). A `/quote` lenta dorme 8s de
  propósito — cortamos antes disso e tentamos de novo, em vez de travar o lead.
- **Retry com backoff exponencial + jitter, só em falha transitória** (timeout, erro
  de conexão, 5xx).
- **422 (cotação recusada) e 400 (payload inválido) NÃO são retry** — são respostas
  determinísticas de negócio. Retry só gastaria tempo. São tratadas diferente dos 5xx.
- **Esgotou as tentativas → `INDISPONIVEL`**, que o agente traduz em handoff pro humano,
  com transparência ao lead. Nunca um preço fabricado.
- Cada tentativa (status, latência, nº de retries) vai pro trace.

### Handoff explícito e defensável
Em [handoff.py](agent/app/handoff.py), os gatilhos são **enumerados em código**, não
escondidos no LLM:

| Gatilho | Quando | Como é detectado |
|---|---|---|
| `api_indisponivel` | `/quote` falhou após os retries | `handoff.from_quote` (código) |
| `cotacao_recusada` | 422 (idade > 75, veículo > 20 anos) — fora da alçada do bot | `handoff.from_quote` (código) |
| `lead_pediu_humano` | lead pediu explicitamente | `handoff.from_text` — marcador `[HANDOFF:humano]` |
| `fora_de_escopo` | assunto que não é cotação de seguro auto | `handoff.from_text` — marcador `[HANDOFF:escopo]` |

Os dois primeiros são **determinísticos** (`from_quote`, a partir do resultado da
cotação); os dois últimos o agente **sinaliza** com um marcador no fim da mensagem,
mapeado por `from_text`. O marcador é removido antes de a resposta chegar ao lead
(`strip_markers`), e o determinístico tem precedência sobre o sinalizado.

### Rastreabilidade
[tracing.py](agent/app/tracing.py) grava um JSONL append-only (`agent/logs/trace.jsonl`),
uma linha por evento (`message` / `quote` / `handoff`) com `conversation_id`, status,
latência e nº de retries. `tail -f trace.jsonl | jq` reconstrói o atendimento inteiro.
Toda PII é mascarada antes de escrever.

### PII
[pii.py](agent/app/pii.py) redige CPF, e-mail, telefone e placa por regex **antes** de
qualquer coisa ir pro log. As mesmas regex extraem o CEP (input legítimo da cotação).
A mesma máscara roda também na indexação do dataset — nada sensível entra no índice.

### Framework e modelo
- **LangGraph** pra orquestração: grafo de estados explícito, **checkpointer durável**
  (estado por `conversation_id`) e `interrupt()` nativo pro handoff (human-in-the-loop).
  O modelo entra por `bind_tools` do LangChain — LangGraph cuida do fluxo/estado; o
  modelo, da extração/decisão; a chamada da `/quote`, do nosso código.
- **Gemini Flash** (`gemini-2.5-flash`) no loop de chat: no **tier gratuito** do Google
  AI Studio — o avaliador roda sem barreira de billing. Acerta o caso-crux (avisar o
  lead com transparência quando a `/quote` cai). `temperature=0` pra respostas estáveis.
  Trocável por outro modelo/provider via `AGENT_MODEL` + o chat model do LangChain,
  sem mexer no grafo.
  > O free tier tem **limite de requisições por dia por modelo**. Se esbarrar
  > (HTTP 429), espere o reset (meia-noite PT) ou troque o `AGENT_MODEL` (ex.:
  > `gemini-2.5-flash-lite`, mais cota — porém mais fraco nos casos de borda).

### Memória durável
Checkpointer do LangGraph em **Postgres** (`PostgresSaver`). O estado do grafo é
guardado como dicts JSON-serializáveis, então a conversa sobrevive a restart.

### Few-shot (RAG)
[agent.py](agent/app/agent.py) injeta no system prompt as conversas passadas que
**converteram** (`outcome='ganho'`) mais parecidas com a fala do lead, buscadas por
similaridade no **pgvector** (mesmo Postgres). Embedding local via `fastembed` (CPU).

**Ressalva:** no dataset, temos os preços sem ter a confirmação de que foram consultados da
API. Usar isso cru como "bom exemplo" ensinaria o agente a fabricar preço —
exatamente o que o desafio penaliza. Por isso o few-shot: (1) filtra só `ganho`,
(2) **remove os preços** dos exemplos, (3) instrui explicitamente *"aprenda o tom/objeção,
NUNCA cite preço — sempre cote pela tool"*. É few-shot de **estilo**, não de comportamento
de cotação. Desligável com `FEWSHOT_ENABLED=0`.

### Local-first
A resolução roda **100% local** (Docker). Cheguei a desenhar o caminho de produção
na Azure, mas o mantive fora do código pra não pesar a legibilidade (IaC/nuvem não
eram requisito). Ver [Próximos passos](#próximos-passos-produção).

---

## Como a solução atende os critérios

| Critério (do enunciado) | Onde |
|---|---|
| Funciona de ponta a ponta | `docker compose up` + `POST /webhook`; grafo conversa→cota→decide |
| **O que faz quando a `/quote` falha** | `quote_client.py`: retry/backoff em 5xx/timeout, nunca inventa preço, esgotou → handoff |
| Handoff explícito e defensável | `handoff.py`: gatilhos enumerados |
| Dá pra rastrear | `tracing.py`: JSONL por mensagem/cotação/handoff, com id e status |
| Cuidado com PII | `pii.py`: masking antes de logar e de indexar |
| Qualidade / legibilidade | módulos coesos, um caminho só, decisões documentadas aqui |

---

## Avaliação em cima do dataset

[eval/run_eval.py](agent/eval/run_eval.py) usa o mesmo índice (do passo 3 de
[Como rodar](#como-rodar-docker)) pra responder *"quando o lead reclamou de X, o que
costumou acontecer?"* — agregando o desfecho das conversas mais parecidas com cada
objeção. Serve de insumo pro few-shot e pra entender padrões de objeção.

```bash
cd agent && uv run python -m eval.run_eval
```

> Nota honesta: como as conversas são sintéticas e o desfecho é atribuído
> proceduralmente (não causal), o valor analítico é limitado — o uso principal do
> dataset aqui é o few-shot de tom/objeção.

---

## Log de execução

Cada execução grava `agent/logs/trace.jsonl`. Formato (uma linha por evento):

```jsonl
{"type":"message","conversation_id":"c1","role":"lead","text":"quero seguro, tenho 35 anos, cpf ***.***.***-**","ts":"..."}
{"type":"quote","conversation_id":"c1","request":{"plano_id":"completo","idade":35,"veiculo_ano":2022,"cep":"01310-100"},"outcome":"ok","retries":2,"premio_mensal":209.9,"attempts":[{"n":1,"status":503,"latency_ms":40,"error":"upstream"},{"n":2,"status":null,"latency_ms":5002,"error":"TimeoutException"},{"n":3,"status":200,"latency_ms":38}],"ts":"..."}
{"type":"message","conversation_id":"c1","role":"agente","text":"Fechou! O plano Completo fica ...","ts":"..."}
```

O exemplo acima mostra o caso que mais importa: a `/quote` **falhou (503) e deu timeout**,
o cliente **tentou de novo** e só então saiu a cotação — com CPF **mascarado** no trace.
Se as tentativas esgotassem, sairia um evento `handoff` (`reason: api_indisponivel`) em
vez de um preço.

O `agent/logs/trace.jsonl` versionado é uma execução real ponta a ponta com **5
cenários**, cobrindo o caminho feliz e os quatro motivos de handoff:

| Conversa | O que acontece | Desfecho |
|---|---|---|
| `s1-feliz` | dados completos + PII no input | cotação **R$ 241,38** (PII mascarada, carência avisada) |
| `s2-apidown` | `/quote` fora do ar (`502/503/503`) | `handoff: api_indisponivel` — **sem preço inventado** |
| `s3-recusada` | lead com 80 anos → `422` | `handoff: cotacao_recusada` |
| `s4-humano` | lead pede atendente humano | `handoff: lead_pediu_humano` |
| `s5-escopo` | lead pergunta de plano de saúde | `handoff: fora_de_escopo` |

Para regenerar um log real de ponta a ponta, suba o stack com uma `GOOGLE_API_KEY`
válida e rode as conversas acima no `/webhook`.

---

## Próximos passos (produção)

A mesma base sobe na nuvem trocando implementações **por configuração**, sem fork da
lógica (foi por isso que o estado do grafo é serializável e o retrieval tem interface
estável):

- **Memória** → Postgres gerenciado (só muda a connection string).
- **Retrieval/few-shot** → um vector store gerenciado (ex.: Azure AI Search) no lugar do pgvector.
- **Canal** → WhatsApp real (ex.: Azure Communication Services / Meta) entregando no `/webhook`.
- **Deploy do agent e API** → containers gerenciados + secrets em cofre.

Mantive isso como narrativa, não como código, pra a entrega ficar focada no que é avaliado.

---

## Estrutura do repositório

```
agent/                 # a solução
  app/                 # agente (grafo, resiliência, pii, tracing, handoff, webhook)
  eval/                # indexação (pgvector) + análise de objeção
  Dockerfile
docker-compose.yml     # quote-api + postgres(pgvector) + agent + indexer(profiled)
quote-service/         # mock instável da /quote (insumo do desafio)
dataset/               # conversas sintéticas + dicionário (insumo do desafio)
DESAFIO.md             # enunciado original
```
