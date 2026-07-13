from __future__ import annotations
import sys
from pathlib import Path
import yaml
from app.core.retriever import retrieve

MIN_HIT_RATE = 0.8
def main() -> int:
    cases = yaml.safe_load((Path(__file__).parent / "test_questions.yaml").read_text(encoding="utf-8"))
    hits = 0
    for case in cases:
        q, expected = case["question"], case["expected_source"]
        chunks = retrieve(q)
        found = any( expected.lower() in str(c.get("payload", {}).get("source", "")).lower() or expected.lower() in str(c.get("payload", {}).get("title", "")).lower()
            for c in chunks)
        hints += found
    rate = hints/ len(cases) if cases else 0.0
    print(f"\nHit rate: {hits}/{len(cases)} = {rate:.0%} (мин. {MIN_HIT_RATE:.0%})")
    return 0 if rate >= MIN_HIT_RATE else 1

if __name__ == "__main__":
    sys.exit(main())
