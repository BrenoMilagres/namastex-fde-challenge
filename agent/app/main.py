from __future__ import annotations
import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import handoff, tracing
from .agent import handle_message

logger = logging.getLogger("autoseguro.webhook")

app = FastAPI(title="AutoSeguro Agent", version="0.1.0")

_FALLBACK_REPLY = (
    "Opa, tivemos uma instabilidade momentanea por aqui. Ja vou te transferir para "
    "um de nossos atendentes concluir o seu atendimento. 🙏"
)


class InboundMessage(BaseModel):
    conversation_id: str = Field(..., description="Id estavel da conversa (lead).")
    message: str = Field(..., description="Texto enviado pelo lead.")


class OutboundReply(BaseModel):
    conversation_id: str
    reply: str
    handed_off: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook", response_model=OutboundReply)
def webhook(msg: InboundMessage):
    try:
        reply = handle_message(msg.conversation_id, msg.message)
        return OutboundReply(
            conversation_id=msg.conversation_id,
            reply=reply.text,
            handed_off=reply.handed_off,
        )
    except Exception:
        logger.exception("Falha ao processar a conversa '%s'", msg.conversation_id)
        tracing.handoff(msg.conversation_id, handoff.HandoffReason.ERRO_INTERNO.value)
        tracing.message(msg.conversation_id, "agente", _FALLBACK_REPLY)
        return OutboundReply(
            conversation_id=msg.conversation_id,
            reply=_FALLBACK_REPLY,
            handed_off=True,
        )
