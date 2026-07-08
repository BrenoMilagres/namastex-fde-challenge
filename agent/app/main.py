"""Webhook FastAPI — interface do agente.

POST /webhook   { conversation_id, message } -> { reply, handed_off }
GET  /health    health check

Simula o canal de WhatsApp: um provedor faz POST a cada mensagem do lead e a
gente responde. O estado da conversa vive no checkpointer do LangGraph (ver
agent.py), indexado por conversation_id.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .agent import handle_message

app = FastAPI(title="AutoSeguro Agent", version="0.1.0")


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
    reply = handle_message(msg.conversation_id, msg.message)
    return OutboundReply(
        conversation_id=msg.conversation_id,
        reply=reply.text,
        handed_off=reply.handed_off,
    )
