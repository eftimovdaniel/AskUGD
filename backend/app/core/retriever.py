from __future__ import annotations
import logging
from app.config import settings
from app.core import rerank as reranker
from app.core import vectorstore
from app.core.translate import translate_query

logger = logging.getLogger(__name__)


class RetrievalUnavailable(Exception):
    """Векторската база / embeddings не се достапни — API треба да врати 503."""

def _query_variants(prashanje: str) -> list[str]:
    varijanti = [prashanje]
    prevod = translate_query(prashanje)
    if prevod and prevod.lower() != prashanje.lower():
        varijanti.append(prevod)
    return varijanti[: settings.max_retrieval_iterations]

def retrieve(prashanje: str) -> list[dict]:
    videni: dict[str, dict] = {}
    varijanti = _query_variants(prashanje)
    neuspesi = 0
    for varijanta_br, varijanta in enumerate(varijanti, 1):
        try:
            pogodoci = vectorstore.search(varijanta, limit=settings.candidate_k)
        except Exception as greshka: 
            neuspesi += 1
            logger.error("Search за варијанта %d падна: %s", varijanta_br, greshka)
            continue
        for pogodok in pogodoci:
            prethoden = videni.get(pogodok["id"])
            if prethoden is None or pogodok["score"] > prethoden["score"]:
                videni[pogodok["id"]] = pogodok
        if len(videni) >= settings.candidate_k:
            break
    if neuspesi == len(varijanti):
        raise RetrievalUnavailable("Пребарувањето е недостапно (Qdrant/embeddings)")

    kandidati = sorted(videni.values(), key=lambda pogodok: pogodok["score"], reverse=True)
    kandidati = kandidati[: settings.candidate_k]
    if not kandidati:
        return []
    oceni = reranker.rerank(prashanje, [kand["text"] for kand in kandidati])
    if oceni is not None:
        for kandidat, ocena in zip(kandidati, oceni, strict=True):
            kandidat["rerank_score"] = ocena
        kandidati = [kandidat for kandidat in kandidati
                      if kandidat["rerank_score"] >= settings.rerank_threshold]
        kandidati.sort(key=lambda kand: kand["rerank_score"], reverse=True)
    najdobri = kandidati[: settings.top_k]
    logger.info("Retrieval: %d кандидати → %d по rerank/threshold", len(videni), len(najdobri))
    return najdobri

def extract_sources(parchinja: list[dict]) -> list[dict]:
    izvori, videni_klucevi = [], set()
    for parche in parchinja:
        podatoci = parche.get("payload", {})
        kluc = (podatoci.get("source"), podatoci.get("article_no"))
        if kluc in videni_klucevi:
            continue
        videni_klucevi.add(kluc)
        izvori.append({
            "title": podatoci.get("title") or podatoci.get("source") or "?",
            "url": podatoci.get("url"),
            "article_no": podatoci.get("article_no"),
            "source": podatoci.get("source") or "?",
        })
    return izvori
