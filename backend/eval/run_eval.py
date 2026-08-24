## Retrieval eval. Start:  .venv/bin/python eval/run_eval.py
## so --answers: dodatno generira odgovor i proveruva must_contain_answer (bara LLM).
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import yaml
from app.core.retriever import retrieve

MIN_HIT_RATE = 0.8


def _najde_izvor(parchinja: list[dict], ocekuvano: str) -> bool:
    kluc = ocekuvano.lower()
    return any(
        kluc in str(parche.get("payload", {}).get("source", "")).lower()
        or kluc in str(parche.get("payload", {}).get("title", "")).lower()
        for parche in parchinja
    )


def _ima_frazi(tekst: str, frazi: list[str]) -> bool:
    nizok = tekst.lower()
    return all(fraza.lower() in nizok for fraza in frazi)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AskUGD retrieval/answer eval")
    parser.add_argument("--answers", action="store_true",
                        help="генерирај одговор и провери must_contain_answer")
    args = parser.parse_args(argv)

    slucai = yaml.safe_load(
        (Path(__file__).parent / "test_questions.yaml").read_text(encoding="utf-8")
    )
    pogodoci = 0
    fact_ok = 0
    fact_vkupno = 0
    for slucaj in slucai:
        prashanje, ocekuvano = slucaj["question"], slucaj["expected_source"]
        parchinja = retrieve(prashanje)
        najdeno = _najde_izvor(parchinja, ocekuvano)
        pogodoci += najdeno
        print(
            f"{'yes' if najdeno else 'no'}  {prashanje!r} -> "
            f"{[parche.get('payload', {}).get('source') for parche in parchinja]}"
        )
        if slucaj.get("must_contain"):
            fact_vkupno += 1
            tekst = " ".join(parche.get("text") or "" for parche in parchinja)
            ok = _ima_frazi(tekst, slucaj["must_contain"])
            fact_ok += ok
            print(f"  chunk-fact={'yes' if ok else 'no'}  {slucaj['must_contain']}")
        if args.answers and slucaj.get("must_contain_answer"):
            from app.core.generator import generate
            fact_vkupno += 1
            odgovor = generate(prashanje, parchinja) if parchinja else ""
            ok = _ima_frazi(odgovor, slucaj["must_contain_answer"])
            fact_ok += ok
            print(f"  answer-fact={'yes' if ok else 'no'}  {odgovor[:80]!r}")

    stapka = pogodoci / len(slucai) if slucai else 0.0
    print(f"\nHit stapka: {pogodoci}/{len(slucai)} = {stapka:.0%} (мин. {MIN_HIT_RATE:.0%})")
    if fact_vkupno:
        print(f"Fact stapka: {fact_ok}/{fact_vkupno} = {fact_ok / fact_vkupno:.0%}")
        if fact_ok < fact_vkupno:
            return 1
    return 0 if stapka >= MIN_HIT_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
