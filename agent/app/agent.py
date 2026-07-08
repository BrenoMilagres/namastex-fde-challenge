"""Orquestracao do agente com LangGraph.

Por que LangGraph: grafo de estados explicito, checkpointer duravel (estado por
conversation_id, no Postgres) e human-in-the-loop de verdade (`interrupt()`) pro
handoff. O MODELO e um Gemini via LangChain (`ChatGoogleGenerativeAI`) — escolhido
por ter tier gratis no Google AI Studio, entao o avaliador roda sem barreira.
LangGraph cuida do fluxo/estado; a extracao/decisao ficam com o modelo; a chamada
da /quote e a resiliencia ficam no nosso codigo (quote_client).

Grafo:

    START -> model --(tool_calls?)--> quote --> model   (loop de cotacao)
                   \\--(texto)--------> respond --(handoff?)--> handoff -> END
                                                  \\--------------------> END
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from . import config, handoff, tracing
from .quote_client import QuoteOutcome, QuoteResult, cotar
from .tools import COTAR_TOOL, SYSTEM_PROMPT


# Modelo de chat: Gemini (GOOGLE_API_KEY). temperature=0 pra respostas estaveis.
_llm = ChatGoogleGenerativeAI(
    model=config.AGENT_MODEL,
    temperature=0,
    max_output_tokens=config.AGENT_MAX_TOKENS,
).bind_tools([COTAR_TOOL])


class State(TypedDict):
    # `add_messages` acumula/mescla mensagens LangChain ao longo da conversa. O
    # checkpointer persiste esse historico por thread_id (conversation_id).
    messages: Annotated[list, add_messages]
    conversation_id: str
    forced_handoff: str | None   # gatilho de handoff vindo da cotacao (por turno)
    handed_off: bool


@dataclass
class AgentReply:
    text: str
    handed_off: bool = False


# --- Nos do grafo ---

def _call_model(state: State) -> dict:
    # System prompt e reconstruido a cada chamada (com few-shot fresco) e NAO fica
    # no historico — evita duplicar/inflar o estado persistido.
    system = SYSTEM_PROMPT + _fewshot_block(state)
    resp = _llm.invoke([SystemMessage(content=system), *state["messages"]])
    return {"messages": [resp]}


_PRICE_RE = re.compile(r"R\$\s?\d[\d.]*,\d{2}")


def _fewshot_block(state: State) -> str:
    """Injeta no system prompt K conversas passadas que CONVERTERAM, parecidas com
    a ultima fala do lead. So roda em turno real do lead (HumanMessage) e degrada
    em silencio se o retrieval/indice nao estiver disponivel — nunca quebra a
    conversa. Precos sao removidos: o exemplo ensina TOM/objecao, nao a inventar
    valor (o agente sempre cota pela tool)."""
    if not config.FEWSHOT_ENABLED:
        return ""
    last = state["messages"][-1]
    if not isinstance(last, HumanMessage) or not isinstance(last.content, str):
        return ""

    try:
        from . import retrieval
        hits = retrieval.search_similar(last.content, k=config.FEWSHOT_K, outcome="ganho")
    except Exception:
        return ""  # indice ausente / retrieval fora do ar -> segue sem few-shot
    if not hits:
        return ""

    exemplos = []
    for i, h in enumerate(hits, 1):
        txt = _PRICE_RE.sub("R$ [omitido]", h["text"])[:500]
        exemplos.append(f"Exemplo {i} ({h['veiculo_texto']}):\n{txt}")

    return (
        "\n\n<exemplos_que_converteram>\n"
        "Conversas passadas que fecharam venda, parecidas com a do lead atual. "
        "Use como referencia de TOM e de como conduzir/contornar objecao. NAO "
        "copie precos nem afirme valor: voce SEMPRE cota pela tool `cotar` e nunca "
        "diz um preco que nao veio dela.\n\n"
        + "\n\n".join(exemplos)
        + "\n</exemplos_que_converteram>"
    )


def _run_quotes(state: State) -> dict:
    """Executa cada chamada de `cotar` com o cliente resiliente, registra o trace
    e detecta handoff deterministico. Devolve os ToolMessage pro modelo formatar."""
    cid = state["conversation_id"]
    last = state["messages"][-1]  # AIMessage com tool_calls
    forced = state.get("forced_handoff")
    tool_msgs = []

    for tc in last.tool_calls:
        if tc["name"] != "cotar":
            continue
        payload = dict(tc["args"])
        result = cotar(payload)
        tracing.quote(cid, payload, result)

        reason = handoff.from_quote(result)
        if reason:
            forced = reason.value
            tracing.handoff(cid, reason.value, result.motivo)

        tool_msgs.append(ToolMessage(content=_tool_result_text(result), tool_call_id=tc["id"]))

    return {"messages": tool_msgs, "forced_handoff": forced}


def _respond(state: State) -> dict:
    """Resposta final do turno: extrai o texto, registra e decide se houve handoff."""
    cid = state["conversation_id"]
    text = _last_ai_text(state["messages"])
    forced = state.get("forced_handoff")
    handed = bool(forced)

    # Handoff sinalizado pelo modelo (marcador no texto) -> handoff.from_text.
    reason = handoff.from_text(text)
    if reason:
        text = handoff.strip_markers(text)
        handed = True

        if not forced:
            tracing.handoff(cid, reason.value)

    tracing.message(cid, "agente", text)
    return {"handed_off": handed}


def _human_handoff(state: State) -> dict:
    """Human-in-the-loop idiomatico do LangGraph: pausa o grafo ate um humano
    assumir. O checkpointer preserva o estado; retomar = invocar com
    Command(resume=<mensagem do humano>). Aqui so sinalizamos a pausa."""
    interrupt({
        "reason": state.get("forced_handoff") or "handoff",
        "conversation_id": state["conversation_id"],
    })
    return {}


# --- Roteamento ---

def _route_after_model(state: State) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "quote"
    return "respond"


def _route_after_respond(state: State) -> str:
    return "handoff" if state.get("handed_off") else "end"


# --- Build ---

def _make_checkpointer():
    """Persiste o estado do grafo por conversation_id no Postgres, sobrevivendo a
    restart do processo. Pool de conexoes com autocommit + dict_row (exigidos pelo
    saver); `.setup()` cria as tabelas do checkpointer (idempotente)."""
    if not config.POSTGRES_URL:
        raise RuntimeError(
            "POSTGRES_URL nao setado. Suba o banco com `docker compose up` e "
            "copie .env.example para .env."
        )

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        conninfo=config.POSTGRES_URL,
        max_size=10,
        open=True,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


def _build():
    g = StateGraph(State)
    g.add_node("model", _call_model)
    g.add_node("quote", _run_quotes)
    g.add_node("respond", _respond)
    g.add_node("handoff", _human_handoff)

    g.add_edge(START, "model")
    g.add_conditional_edges("model", _route_after_model, {"quote": "quote", "respond": "respond"})
    g.add_edge("quote", "model")
    g.add_conditional_edges("respond", _route_after_respond, {"handoff": "handoff", "end": END})
    g.add_edge("handoff", END)

    return g.compile(checkpointer=_make_checkpointer())


_graph = _build()


def handle_message(conversation_id: str, text: str) -> AgentReply:
    """Ponto de entrada: processa um turno do lead e devolve a resposta do agente.
    O estado da conversa vive no checkpointer, indexado por conversation_id."""
    tracing.message(conversation_id, "lead", text)
    cfg = {"configurable": {"thread_id": conversation_id}}
    state = _graph.invoke(
        {
            "messages": [HumanMessage(content=text)],
            "conversation_id": conversation_id,
            "forced_handoff": None,
            "handed_off": False,
        },
        cfg,
    )
    # strip_markers e o unico sanitizador: garante que nenhum marcador [HANDOFF...]
    # vaze pro lead (o AIMessage no state ainda tem o marcador cru; _respond so o
    # remove pro trace). Idempotente quando nao ha marcador.
    reply = handoff.strip_markers(_last_ai_text(state["messages"]))
    handed = bool(state.get("handed_off")) or "__interrupt__" in state
    return AgentReply(text=reply, handed_off=handed)


# --- Helpers ---

def _last_ai_text(messages: list) -> str:
    for m in reversed(messages):
        if not isinstance(m, AIMessage):
            continue
        content = m.content
        if isinstance(content, str):
            if content.strip():
                return content.strip()
        elif isinstance(content, list):  # blocos (raro no Gemini) -> junta os textos
            parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
            joined = "".join(parts).strip()
            if joined:
                return joined
    return ""


def _tool_result_text(result: QuoteResult) -> str:
    """Traduz o QuoteResult em texto pro modelo formatar a resposta ao lead. Guia o
    comportamento por outcome — nos casos de handoff, instrui a ser transparente
    sem prometer nada nem inventar preco."""
    if result.outcome == QuoteOutcome.OK:
        return json.dumps(result.data, ensure_ascii=False)
    if result.outcome == QuoteOutcome.RECUSADA:
        return (
            f"COTACAO_RECUSADA: {result.motivo}. Explique ao lead com empatia que "
            "esse perfil precisa de analise de um atendente humano, que vai assumir."
        )
    if result.outcome == QuoteOutcome.INVALIDO:
        return (
            f"DADOS_INVALIDOS: {result.motivo}. Peca ao lead pra confirmar os dados "
            "(idade e ano do veiculo) antes de tentar cotar de novo."
        )
    # INDISPONIVEL
    return (
        "SISTEMA_INDISPONIVEL: a cotacao esta temporariamente fora do ar apos "
        "varias tentativas. NAO invente preco. Avise o lead com transparencia que "
        "um atendente humano vai concluir a cotacao em instantes."
    )
