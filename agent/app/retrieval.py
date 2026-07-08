"""Retrieval do historico de conversas via pgvector (no mesmo Postgres).

As conversas antigas (mascaradas) vivem numa tabela `conversas` com uma coluna
`embedding vector(N)`. A busca por similaridade e SQL puro (`<=>` = distancia
cosseno). Usado pelo few-shot do agente (agent.py) e pela analise (eval/run_eval).

Embedding local via fastembed (ONNX, CPU) — sem nuvem, sem key. O modelo e
carregado uma vez e cacheado.
"""
from __future__ import annotations

from . import config

_emb_model = None


def _model():
    global _emb_model
    if _emb_model is None:
        from fastembed import TextEmbedding
        _emb_model = TextEmbedding(config.EMBED_MODEL)
    return _emb_model


def embed_many(texts: list[str]) -> list[list[float]]:
    return [[float(x) for x in v] for v in _model().embed(list(texts))]


def embed_one(text: str) -> list[float]:
    return embed_many([text])[0]


def _vec_literal(v: list[float]) -> str:
    """Formato textual do pgvector: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def search_similar(query: str, k: int = 5, outcome: str | None = None) -> list[dict]:
    """Conversas passadas mais parecidas com `query` (distancia cosseno no
    pgvector). Filtra por desfecho quando `outcome` e dado."""
    import psycopg

    qv = _vec_literal(embed_one(query))
    sql = """
        SELECT conversation_id, outcome, veiculo_texto, idade, text
        FROM conversas
        WHERE (%(outcome)s::text IS NULL OR outcome = %(outcome)s::text)
        ORDER BY embedding <=> %(qv)s::vector
        LIMIT %(k)s
    """
    cols = ["conversation_id", "outcome", "veiculo_texto", "idade", "text"]
    with psycopg.connect(config.POSTGRES_URL) as conn:
        rows = conn.execute(sql, {"outcome": outcome, "qv": qv, "k": k}).fetchall()
    return [dict(zip(cols, r)) for r in rows]
