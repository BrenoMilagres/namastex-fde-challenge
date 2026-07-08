from __future__ import annotations
import os

QUOTE_API_URL = os.getenv("QUOTE_API_URL", "http://localhost:8000")

QUOTE_TIMEOUT_SECONDS = float(os.getenv("QUOTE_TIMEOUT_SECONDS", "5"))

QUOTE_MAX_RETRIES = int(os.getenv("QUOTE_MAX_RETRIES", "3"))
QUOTE_BACKOFF_BASE_SECONDS = float(os.getenv("QUOTE_BACKOFF_BASE_SECONDS", "0.5"))
QUOTE_BACKOFF_MAX_SECONDS = float(os.getenv("QUOTE_BACKOFF_MAX_SECONDS", "4"))

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")
AGENT_MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", "1024"))

POSTGRES_URL = os.getenv("POSTGRES_URL")

EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBED_DIMS = int(os.getenv("EMBED_DIMS", "384"))

FEWSHOT_ENABLED = os.getenv("FEWSHOT_ENABLED", "1") != "0"
FEWSHOT_K = int(os.getenv("FEWSHOT_K", "2"))

TRACE_LOG_PATH = os.getenv("TRACE_LOG_PATH", "logs/trace.jsonl")
