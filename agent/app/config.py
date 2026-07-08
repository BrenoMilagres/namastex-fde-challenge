"""Configuracao central via variaveis de ambiente.

Tudo que muda entre dev/prod (URL da API, modelo, timeouts, politica de retry)
fica aqui — nenhum valor magico espalhado pelo codigo.
"""
from __future__ import annotations
import os

# --- API de cotacao ---
QUOTE_API_URL = os.getenv("QUOTE_API_URL", "http://localhost:8000")

# Timeout por tentativa. A /quote lenta dorme 8s de proposito, entao cortamos
# antes disso: preferimos falhar rapido e tentar de novo a travar o lead 8s.
QUOTE_TIMEOUT_SECONDS = float(os.getenv("QUOTE_TIMEOUT_SECONDS", "5"))

# Retry so em falha transitoria (5xx / timeout). Backoff exponencial com teto.
QUOTE_MAX_RETRIES = int(os.getenv("QUOTE_MAX_RETRIES", "3"))
QUOTE_BACKOFF_BASE_SECONDS = float(os.getenv("QUOTE_BACKOFF_BASE_SECONDS", "0.5"))
QUOTE_BACKOFF_MAX_SECONDS = float(os.getenv("QUOTE_BACKOFF_MAX_SECONDS", "4"))

# --- Modelo (Gemini via LangChain) ---
# gemini-2.5-flash: melhor no ponto-crux (avisar o lead com transparencia quando a
# /quote cai). Tier GRATIS do Google AI Studio, sem cartao. O free tier tem cota
# diaria baixa POR modelo; se esbarrar (429), troque via AGENT_MODEL (ex.:
# gemini-2.5-flash-lite tem mais cota, porem mais fraco). Key: GOOGLE_API_KEY.
AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")
AGENT_MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", "1024"))

# --- Memoria / checkpointer do LangGraph ---
# Estado da conversa persistido no Postgres (PostgresSaver) — o do docker-compose
# em dev. Obrigatorio: sem ele o agente nao sobe (ver agent._make_checkpointer).
POSTGRES_URL = os.getenv("POSTGRES_URL")

# --- Retrieval / few-shot (pgvector no mesmo Postgres) ---
# Embedding local (fastembed/ONNX, CPU). Modelo multilingue porque os dados sao
# PT-BR. As conversas antigas ficam numa tabela `conversas` com coluna vector.
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBED_DIMS = int(os.getenv("EMBED_DIMS", "384"))

# Few-shot: injeta K conversas que CONVERTERAM, parecidas com a fala do lead, no
# system prompt (so tom/objecao; precos sao removidos — ver agent.py). Desligar
# com FEWSHOT_ENABLED=0 se quiser o hot path minimo.
FEWSHOT_ENABLED = os.getenv("FEWSHOT_ENABLED", "1") != "0"
FEWSHOT_K = int(os.getenv("FEWSHOT_K", "2"))

# --- Tracing ---
TRACE_LOG_PATH = os.getenv("TRACE_LOG_PATH", "logs/trace.jsonl")
