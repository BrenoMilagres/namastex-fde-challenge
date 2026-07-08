from __future__ import annotations
import random
import time
from dataclasses import dataclass, field
from enum import Enum

import httpx

from . import config


class QuoteOutcome(str, Enum):
    OK = "ok"
    RECUSADA = "recusada"
    INVALIDO = "invalido"
    INDISPONIVEL = "indisponivel"


@dataclass
class Attempt:
    n: int
    status: int | None
    latency_ms: int
    error: str | None = None


@dataclass
class QuoteResult:
    outcome: QuoteOutcome
    data: dict | None = None
    motivo: str | None = None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def retries(self) -> int:
        return max(0, len(self.attempts) - 1)


def _backoff(n: int) -> float:
    raw = config.QUOTE_BACKOFF_BASE_SECONDS * (2 ** n)
    return min(raw, config.QUOTE_BACKOFF_MAX_SECONDS) + random.uniform(0, 0.25)


def cotar(payload: dict) -> QuoteResult:
    """Chama POST /quote com retry resiliente. Sempre retorna QuoteResult —
    nunca levanta excecao pro chamador nem inventa dado."""
    url = f"{config.QUOTE_API_URL}/quote"
    attempts: list[Attempt] = []

    for n in range(config.QUOTE_MAX_RETRIES):
        started = time.monotonic()
        try:
            resp = httpx.post(url, json=payload, timeout=config.QUOTE_TIMEOUT_SECONDS)
            latency = int((time.monotonic() - started) * 1000)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            latency = int((time.monotonic() - started) * 1000)
            attempts.append(Attempt(n=n + 1, status=None, latency_ms=latency, error=type(e).__name__))
            if n + 1 < config.QUOTE_MAX_RETRIES:
                time.sleep(_backoff(n))
            continue

        if resp.status_code == 200:
            attempts.append(Attempt(n=n + 1, status=200, latency_ms=latency))
            return QuoteResult(QuoteOutcome.OK, data=resp.json(), attempts=attempts)
        if resp.status_code == 422:
            attempts.append(Attempt(n=n + 1, status=422, latency_ms=latency))
            motivo = resp.json().get("motivo", "Cotacao recusada.")
            return QuoteResult(QuoteOutcome.RECUSADA, motivo=motivo, attempts=attempts)
        if resp.status_code == 400:
            attempts.append(Attempt(n=n + 1, status=400, latency_ms=latency))
            detalhe = resp.json().get("detalhe", "Payload invalido.")
            return QuoteResult(QuoteOutcome.INVALIDO, motivo=detalhe, attempts=attempts)

        attempts.append(Attempt(n=n + 1, status=resp.status_code, latency_ms=latency, error="upstream"))
        if n + 1 < config.QUOTE_MAX_RETRIES:
            time.sleep(_backoff(n))

    return QuoteResult(QuoteOutcome.INDISPONIVEL, attempts=attempts)
