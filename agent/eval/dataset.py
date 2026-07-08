from __future__ import annotations
import os
from pathlib import Path
import pandas as pd
from app.pii import mask

_DEFAULT = Path(__file__).resolve().parents[2] / "dataset" / "conversations.parquet"
DATASET = Path(os.getenv("DATASET_PATH", str(_DEFAULT)))


def build_documents() -> list[dict]:
    df = pd.read_parquet(DATASET)
    docs = []
    for cid, g in df.groupby("conversation_id"):
        g = g.sort_values("message_index")
        linhas = [f"{r.sender_role}: {mask(str(r.message_body))}" for r in g.itertuples()]
        first = g.iloc[0]
        docs.append({
            "id": str(cid),
            "conversation_id": str(cid),
            "outcome": str(first.conversation_outcome),
            "veiculo_texto": str(first.veiculo_texto),
            "idade": int(first.lead_idade_informada) if pd.notna(first.lead_idade_informada) else 0,
            "text": "\n".join(linhas),
        })
    return docs
