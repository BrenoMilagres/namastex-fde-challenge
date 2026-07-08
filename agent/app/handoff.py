from __future__ import annotations
import re
from enum import Enum

from .quote_client import QuoteOutcome, QuoteResult


class HandoffReason(str, Enum):
    API_INDISPONIVEL = "api_indisponivel"
    COTACAO_RECUSADA = "cotacao_recusada"
    LEAD_PEDIU_HUMANO = "lead_pediu_humano"
    FORA_DE_ESCOPO = "fora_de_escopo"


_MARKERS = {
    "[HANDOFF:humano]": HandoffReason.LEAD_PEDIU_HUMANO,
    "[HANDOFF:escopo]": HandoffReason.FORA_DE_ESCOPO,
}
_MARKER_RE = re.compile(r"\[HANDOFF(?::\w+)?\]")


def from_quote(result: QuoteResult) -> HandoffReason | None:
    """Handoff DETERMINISTICO a partir do resultado da cotacao."""
    if result.outcome == QuoteOutcome.INDISPONIVEL:
        return HandoffReason.API_INDISPONIVEL
    if result.outcome == QuoteOutcome.RECUSADA:
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
