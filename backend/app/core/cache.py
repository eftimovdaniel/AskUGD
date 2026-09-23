# Kes za gotovi odgovori — isto prasanje (bez istorija) bez nov LLM povik.
# In-memory: TTL + LRU. Redis (REDIS_URL): delen megju workers so SETEX.
from __future__ import annotations
import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Any
from app.config import settings
from app.core.language import is_mk_latin, transliterate_mk

logger = logging.getLogger(__name__)
_WS_RE = re.compile(r"\s+")


def normalize_key(question: str) -> str:
    """Ist kluc za „Kolku cini upis“ i „колку чини упис“ — mk-latinica → kirilica."""
    kluc = _WS_RE.sub(" ", question).strip().lower()
    if is_mk_latin(kluc):
        kluc = transliterate_mk(kluc)
    return kluc


class AnswerCache:
    """In-memory LRU + TTL. Eden worker; za povekje → RedisAnswerCache."""
    def __init__(self, max_size: int, ttl_seconds: float) -> None:
        self._max = max_size
        self._ttl = ttl_seconds
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any:
        sega = time.monotonic()
        with self._lock:
            zapis = self._store.get(key)
            if zapis is None:
                self.misses += 1
                return None
            vreme, vrednost = zapis
            if sega - vreme > self._ttl:
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return vrednost

    def set(self, key: str, value: Any) -> None:
        sega = time.monotonic()
        with self._lock:
            self._store[key] = (sega, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            vkupno = self.hits + self.misses
            return {
                "cache_size": len(self._store),
                "cache_hits": self.hits,
                "cache_misses": self.misses,
                "cache_hit_rate": round(self.hits / vkupno, 3) if vkupno else 0.0,
                "cache_backend": "memory",
            }


class RedisAnswerCache:
    """Delen kes megju workers. Pri Redis pad — fallback na in-memory."""

    def __init__(self, url: str, ttl_seconds: int, max_size: int) -> None:
        import redis
        self._ttl = int(ttl_seconds)
        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
        self._fallback = AnswerCache(max_size=max_size, ttl_seconds=ttl_seconds)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def _kluc(self, key: str) -> str:
        # Hash: prasanjeto e do 1000 znaci so razmaci/novi redovi — losh Redis kluc.
        return "ans:" + hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any:
        try:
            surovo = self._r.get(self._kluc(key))
            if surovo is None:
                with self._lock:
                    self.misses += 1
                return None
            podatoci = json.loads(surovo)
            with self._lock:
                self.hits += 1
            return (podatoci["answer"], podatoci.get("sources") or [])
        except Exception as greshka:
            logger.warning("Redis answer cache get падна (%s) — fallback", greshka)
            return self._fallback.get(key)

    def set(self, key: str, value: Any) -> None:
        odgovor, izvori = value
        try:
            payload = json.dumps(
                {"answer": odgovor, "sources": izvori},
                ensure_ascii=False,
            )
            self._r.setex(self._kluc(key), self._ttl, payload)
        except Exception as greshka:
            logger.warning("Redis answer cache set падна (%s) — fallback", greshka)
            self._fallback.set(key, value)

    def delete(self, key: str) -> None:
        self._fallback.delete(key)
        try:
            self._r.delete(self._kluc(key))
        except Exception as greshka:
            logger.warning("Redis answer cache delete падна (%s)", greshka)

    def clear(self) -> None:
        self._fallback.clear()
        try:
            for kluc in self._r.scan_iter(match="ans:*", count=200):
                self._r.delete(kluc)
        except Exception as greshka:
            logger.warning("Redis answer cache clear падна (%s)", greshka)

    def stats(self) -> dict:
        with self._lock:
            vkupno = self.hits + self.misses
            return {
                "cache_size": -1,
                "cache_hits": self.hits,
                "cache_misses": self.misses,
                "cache_hit_rate": round(self.hits / vkupno, 3) if vkupno else 0.0,
                "cache_backend": "redis",
            }


def _make_cache() -> AnswerCache | RedisAnswerCache:
    if settings.redis_url:
        return RedisAnswerCache(
            settings.redis_url,
            ttl_seconds=settings.cache_ttl_seconds,
            max_size=settings.cache_max_size,
        )
    return AnswerCache(
        max_size=settings.cache_max_size,
        ttl_seconds=settings.cache_ttl_seconds,
    )


answer_cache = _make_cache()
