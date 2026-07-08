from __future__ import annotations
import os
import psycopg
from app import config, retrieval
from eval.dataset import build_documents

_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS conversas (
    id              text PRIMARY KEY,
    conversation_id text,
    outcome         text,
    veiculo_texto   text,
    idade           int,
    text            text,
    embedding       vector({config.EMBED_DIMS})
);
CREATE INDEX IF NOT EXISTS conversas_embedding_idx
    ON conversas USING hnsw (embedding vector_cosine_ops);
"""

_UPSERT = """
INSERT INTO conversas (id, conversation_id, outcome, veiculo_texto, idade, text, embedding)
VALUES (%(id)s, %(conversation_id)s, %(outcome)s, %(veiculo_texto)s, %(idade)s, %(text)s, %(embedding)s::vector)
ON CONFLICT (id) DO UPDATE SET
    outcome = EXCLUDED.outcome, veiculo_texto = EXCLUDED.veiculo_texto,
    idade = EXCLUDED.idade, text = EXCLUDED.text, embedding = EXCLUDED.embedding
"""


def main() -> None:
    force = os.getenv("REINDEX") == "1"
    with psycopg.connect(config.POSTGRES_URL, autocommit=True) as conn:
        conn.execute(_DDL)
        count = conn.execute("SELECT count(*) FROM conversas").fetchone()[0]
        if count and not force:
            print(f"ja indexado ({count} conversas) — pulando. REINDEX=1 pra forcar.")
            return

        docs = build_documents()
        print(f"conversas: {len(docs)} — gerando embeddings (fastembed)...")
        vectors = retrieval.embed_many([d["text"] for d in docs])
        for d, v in zip(docs, vectors):
            conn.execute(_UPSERT, {**d, "embedding": retrieval._vec_literal(v)})
    print(f"OK — {len(docs)} conversas indexadas na tabela 'conversas' (pgvector).")


if __name__ == "__main__":
    main()
