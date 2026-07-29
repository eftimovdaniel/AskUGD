#In-memory kes za gotovi odgovori — isto prasanje (bez istorija) se vraka od kes bez nov LLM povik. TTL (istekuvanje) + LRU (frla najstaro) + thread-safe.
# normalize_key pravi isto prasanje so razlicni praznini/bukvi da e ist kluc.
from __future__ import annotations
import re
import threading
import time
from collections import OrderedDict
from typing import Any
from app.config import settings

_WS_RE = re.compile(r"\s+")

def normalize_key(question: str) -> str:
    return _WS_RE.sub(" ", question).strip().lower()
class AnswerCache:
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
            }


answer_cache = AnswerCache(
    max_size=settings.cache_max_size,
    ttl_seconds=settings.cache_ttl_seconds,
)
