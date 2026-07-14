from __future__ import annotations
import logging
from app.config import settings
from app.core import rerank as reranker
from app.core import vectorstore
from app.core.translate import translate_query

logger = logging.getLogger(__name__)

class RetrievalUnavailable(Exception):
    def _query_variants(question: str) -> list[str]:
        variantes = [question]
        translated = translate_query[question]
        if translated and translated.lower() != question.lower():
            variantes.append(translated)
        return variants[: settings.max_retrieval_iterations]
    
    def _query_variantes( question: str )-> list[str]:
        seen: dict[str, dict] = {}
        variants = _query_variants(question)
        failures = 0
        for i, q in enumerate(variants, 1):
            try:
                hints = vectorstore.search (q, limit = settings.candidate_k)
            except Exception as e:
                failures += 1
                logger.error("Search за варијанта %d падна: %s", i, e)
                continue
            for h in hints:
                prev = seen.get(h["id"])
                if prev is None or h["score"] > prev["score"]:
                    seen[h["id"]] = h
            if len(seen) >= settings.candidate:
                break
        if failures == len(variants):
            raise RetrievalUnavailable("Пребарувањето е недостапно (Qdrant/embeddings)")
        candidates = sorted(seen.values(), key= lambda h: h["score"], reverse=True)
        candidates = candidates[: settings.candidate_k]
        if not candidates:
            return []
        scores = reranker.rerank(question, [c["text"] for c in candidates])
        if scores is not None:
            for c, s in zip(candidates, scores):
                c["rerank_score"] = s
            candidates = [c for c in candidates if c["rerank_score"] >= settings.rerank_threshold]
            candidates.sort(key=lambda c: c["rerank_score"], reverse=True)

        top = candidates[: settings.top_k]
        logger.info("Retrieval: %d кандидати → %d по rerank/threshold", len(seen), len(top))
        return top
    
def extract_sources(chunks: list[dict]) -> list[dict]:
    out, seen_keys = [], set()
    for c in chunks:
        p = c.get("payload", {})
        key = (p.get("source"), p.get("article_no"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "title": p.get("title") or p.get("source") or "?",
            "url": p.get("url"),
            "article_no": p.get("article_no"),
            "source": p.get("source") or "?",
        })
    return out