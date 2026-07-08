"""Politica de handoff pro humano

Em vez de deixar o LLM decidir de forma opaca, TODO o handoff passa por aqui, em
duas familias — e cada HandoffReason e efetivamente usado:

  - DETERMINISTICO (decidido pelo codigo, a partir da cotacao):
      from_quote()  -> API_INDISPONIVEL | COTACAO_RECUSADA
  - SINALIZADO PELO MODELO (o agente pede via marcador no texto):
      from_text()   -> LEAD_PEDIU_HUMANO | FORA_DE_ESCOPO

O deterministico tem precedencia (ver agent._respond).
"""
from __future__ import annotations
import re
from enum import Enum

from .quote_client import QuoteOutcome, QuoteResult


class HandoffReason(str, Enum):
    API_INDISPONIVEL = "api_indisponivel"    # /quote falhou apos os retries
    COTACAO_RECUSADA = "cotacao_recusada"    # 422 — risco fora da alcada do bot
    LEAD_PEDIU_HUMANO = "lead_pediu_humano"  # lead pediu falar com uma pessoa
    FORA_DE_ESCOPO = "fora_de_escopo"        # assunto que nao e cotacao de seguro auto


# Marcadores que o modelo pode por no fim da resposta (ver SYSTEM_PROMPT).
_MARKERS = {
    "[HANDOFF:humano]": HandoffReason.LEAD_PEDIU_HUMANO,
    "[HANDOFF:escopo]": HandoffReason.FORA_DE_ESCOPO,
}
_MARKER_RE = re.compile(r"\[HANDOFF(?::\w+)?\]")


def from_quote(result: QuoteResult) -> HandoffReason | None:
    """Handoff DETERMINISTICO a partir do resultado da cotacao."""
    if result.outcome == QuoteOutcome.INDISPONIVEL:
        # Infra falhou: nunca inventar preco -> humano assume.
        return HandoffReason.API_INDISPONIVEL
    if result.outcome == QuoteOutcome.RECUSADA:
        # Recusa por idade/veiculo e uma conversa de excecao pra um humano.
        return HandoffReason.COTACAO_RECUSADA
    return None


def from_text(text: str) -> HandoffReason | None:
    """Handoff SINALIZADO PELO MODELO via marcador no texto. `[HANDOFF]` sem
    sufixo cai em LEAD_PEDIU_HUMANO (fallback tolerante)."""
    for marker, reason in _MARKERS.items():
        if marker in text:
            return reason
    if "[HANDOFF]" in text:
        return HandoffReason.LEAD_PEDIU_HUMANO
    return None


def strip_markers(text: str) -> str:
    """Remove os marcadores [HANDOFF...] antes de mandar a resposta pro lead."""
    return _MARKER_RE.sub("", text).strip()
