"""Cross-enkoder re-ranking со graceful fallback.

Ако моделот не може да се вчита (нема RAM/диск), retrieval продолжува
БЕЗ rerank наместо да падне целиот сервис.
"""
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
            logger.info("Вчитувам reranker %s ...", settings.rerank_model)
            _encoder = TextCrossEncoder(model_name=settings.rerank_model)
        except Exception as greshka:  # noqa: BLE001
            _load_failed = True
            logger.error("Reranker не се вчита (%s) — продолжувам без rerank", greshka)
    return _encoder


def rerank(prashanje: str, dokumenti: list[str]) -> list[float] | None:
    """Врати sigmoid ocena (0..1) по документ, или None ако rerank не е достапен."""
    if not dokumenti:
        return []
    enkoder = _get_encoder()
    if enkoder is None:
        return None
    try:
        surovi_oceni = list(enkoder.rerank(prashanje, dokumenti))
        return [1.0 / (1.0 + math.exp(-ocena)) for ocena in surovi_oceni]
    except Exception as greshka:  # noqa: BLE001
        logger.error("Rerank падна (%s) — продолжувам без rerank", greshka)
        return None
