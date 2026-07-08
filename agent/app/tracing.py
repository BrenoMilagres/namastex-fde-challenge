from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .pii import mask
from .quote_client import QuoteResult


def _write(event: dict) -> None:
    path = Path(config.TRACE_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    event["ts"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def message(conversation_id: str, role: str, text: str) -> None:
    """Uma mensagem (lead ou agente). Texto mascarado."""
    _write({
        "type": "message",
        "conversation_id": conversation_id,
        "role": role,
        "text": mask(text),
    })


def quote(conversation_id: str, payload: dict, result: QuoteResult) -> None:
    """Uma tentativa de cotacao com o resultado e todas as sub-tentativas HTTP."""
    _write({
        "type": "quote",
        "conversation_id": conversation_id,
        "request": payload,
        "outcome": result.outcome.value,
        "retries": result.retries,
        "premio_mensal": (result.data or {}).get("premio_mensal"),
        "motivo": result.motivo,
        "attempts": [
            {"n": a.n, "status": a.status, "latency_ms": a.latency_ms, "error": a.error}
            for a in result.attempts
        ],
    })


def handoff(conversation_id: str, reason: str, detail: str | None = None) -> None:
    """Encaminhamento pro humano, com o gatilho explicito."""
    _write({
        "type": "handoff",
        "conversation_id": conversation_id,
        "reason": reason,
        "detail": mask(detail) if detail else None,
    })
