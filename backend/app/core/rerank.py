from __future__ import annotations
import logging
import math
from app.config import settings

logger = logging.getLogger(__name__)
_encoder = None
_load_failed = False

def _get_encoder():
    global _encoder, _load_failed
    if _encoder is None and not _load_failed:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            logger.info ("Вчитувам reranker %s ...", settings.rerank_model)
            _encoder = TextCrossEncoder(model_name = settings.rerank_model)
        except Exception as error:
            _load_failed = True
            logger.error ("Reranker не се вчита (%s) — продолжувам без rerank", error)
        return _encoder
    
def rerank(query: str, documents: list[str]) -> list[float] | None:
    if not documents:
        return []
    encoder = _get_encoder()
    if encoder is None:
        return None
    try:
        raw_scores = list(encoder.rerank(query, documents))
        return [1.0 / (1.0 + math.exp(score) for score in raw_scores)]
    except Exception as error:
        logger.error("Rerank падна (%s) — продолжувам без rerank", error)
        return None