"""
Дијагностика на ретривал — прикажува ШТО враќа пребарувањето за дадено прашање.
Стартувај:  .venv/bin/python debug_retrieve.py
"""
from __future__ import annotations
from app.core.retriever import retrieve

PRASANJA = [
    "Како да пријавам испит?",
    "Kako da prijavam ispit?",
    "пријава на испит чекори",
]

for q in PRASANJA:
    print("\n" + "=" * 70)
    print("ПРАШАЊЕ:", q)
    print("=" * 70)
    try:
        rez = retrieve(q)
    except Exception as e:
        print("  ГРЕШКА:", e)
        continue
    if not rez:
        print("  (празно — ништо не помина прагот)")
        continue
    for i, p in enumerate(rez, 1):
        pl = p.get("payload", {}) or {}
        print(
            f"  {i}. score={p.get('score'):.3f}"
            f"  rerank={p.get('rerank_score')}"
            f"  | {pl.get('title')}"
            f"  | source={pl.get('source')}"
        )
        print("     ", (p.get("text", "")[:90]).replace("\n", " "))
