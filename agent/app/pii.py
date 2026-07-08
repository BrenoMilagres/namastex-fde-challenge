from __future__ import annotations
import re

CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")
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
