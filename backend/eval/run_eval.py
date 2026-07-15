from __future__ import annotations
import sys
from pathlib import Path
import yaml
from app.core.retriever import retrieve

MIN_HIT_RATE = 0.8

def main() -> int:
    slucai = yaml.safe_load(
        (Path(__file__).parent / "test_questions.yaml").read_text(encoding="utf-8"))
    pogodoci = 0
    for slucaj in slucai:
        prashanje, ocekuvano = slucaj["question"], slucaj["expected_source"]
        parchinja = retrieve(prashanje)
        najdeno = any(
            ocekuvano.lower() in str(parche.get("payload", {}).get("source", "")).lower()
            or ocekuvano.lower() in str(parche.get("payload", {}).get("title", "")).lower()
            for parche in parchinja
        )
        pogodoci += najdeno
        print(f"{'✓' if najdeno else '✗'}  {prashanje!r} -> "
              f"{[parche.get('payload', {}).get('source') for parche in parchinja]}")

    stapka = pogodoci / len(slucai) if slucai else 0.0
    print(f"\nHit stapka: {pogodoci}/{len(slucai)} = {stapka:.0%} (мин. {MIN_HIT_RATE:.0%})")
    return 0 if stapka >= MIN_HIT_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
