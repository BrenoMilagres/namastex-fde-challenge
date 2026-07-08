"""Mascaramento de PII para texto livre de WhatsApp.

Os dados sensiveis (CPF, e-mail, telefone, placa) aparecem soltos no meio das
mensagens em formatos variados. Aqui a gente redige ANTES de qualquer coisa ir
pro log ou pra um sistema externo. As mesmas regex servem pra extrair CEP, que
o agente precisa pra cotar (papel duplo: extracao + masking).

Decisao: mascarar de forma parcial (mostra o suficiente pra rastrear/confirmar
com o lead sem expor o dado inteiro). O CEP NAO e mascarado nos logs de negocio
porque e input legitimo da cotacao — mas nunca guardamos CPF/telefone/e-mail.
"""
from __future__ import annotations
import re

# Formatos plausiveis vistos no dataset. Propositalmente tolerantes.
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Telefone BR: +55 DDD 9XXXX-XXXX e variacoes com/sem +55, espaco, hifen.
PHONE_RE = re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")
# Placa: ABC1234 (antiga) ou ABC1D23 (Mercosul).
PLATE_RE = re.compile(r"\b[A-Z]{3}\d[A-Z0-9]\d{2}\b")
CEP_RE = re.compile(r"\b\d{5}-?\d{3}\b")


def _mask_cpf(m: re.Match) -> str:
    return "***.***.***-**"


def _mask_email(m: re.Match) -> str:
    local, _, domain = m.group(0).partition("@")
    shown = local[0] if local else "*"
    return f"{shown}***@{domain}"


def _mask_phone(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return f"***-{digits[-4:]}" if len(digits) >= 4 else "***"


def _mask_plate(m: re.Match) -> str:
    p = m.group(0)
    return f"{p[:3]}****"


def mask(text: str) -> str:
    """Redige CPF, e-mail, telefone e placa. Preserva CEP (input de cotacao)."""
    text = CPF_RE.sub(_mask_cpf, text)
    text = EMAIL_RE.sub(_mask_email, text)
    text = PHONE_RE.sub(_mask_phone, text)
    text = PLATE_RE.sub(_mask_plate, text)
    return text


def extract_cep(text: str) -> str | None:
    """Primeiro CEP encontrado, normalizado como NNNNN-NNN."""
    m = CEP_RE.search(text)
    if not m:
        return None
    d = re.sub(r"\D", "", m.group(0))
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else None
