from __future__ import annotations
from collections import Counter
from app import retrieval

OBJECOES = [
    "o preco ta salgado, achei caro",
    "vi mais barato na concorrente",
    "preciso pensar, vou ver com minha esposa",
    "a franquia ta muito alta",
    "quero falar com um atendente de verdade",
]


def main() -> None:
    for objecao in OBJECOES:
        hits = retrieval.search_similar(objecao, k=10)
        desfechos = Counter(h["outcome"] for h in hits)
        print(f"\nOBJECAO: {objecao!r}")
        print(f"  desfechos das {len(hits)} conversas mais parecidas: {dict(desfechos)}")
        exemplo = next((h for h in hits if h["outcome"] == "ganho"), None)
        if exemplo:
            print(f"  ex. que converteu (conv {exemplo['conversation_id']}): "
                  f"{exemplo['text'][:160].replace(chr(10), ' / ')}...")


if __name__ == "__main__":
    main()
