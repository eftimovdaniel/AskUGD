"""Безбедносен слој: rate limiting, API key, чистење на влез, injection guard.

Rate limiting е на ДВЕ нивоа:
- по сесија (rate_limit) — фер лимит по корисник
- по IP (rate_limit_ip, повисок) — кампус NAT значи стотици студенти зад
  иста јавна IP, па нискиот IP лимит би ги блокирал масовно

Ако REDIS_URL е поставен, лимитите се споделени меѓу workers/replika.
"""
from __future__ import annotations

import hmac
import logging
import re
import threading
import time
from collections import defaultdict, deque

from app.config import settings

logger = logging.getLogger(__name__)

# Контролни карактери освен \n и \t
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Типични prompt-injection фрази во ПРАШАЊЕ (mk + en) — се логираат и неутрализираат
_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"disregard\s+(the\s+)?(above|previous|prior)|"
    r"you\s+are\s+sega\b|act\s+as\s+(a|an)\b|new\s+instructions?\s*:|"
    r"system\s*prompt|developer\s+message|reveal\s+your\s+(instructions|prompt)|"
    r"игнорирај\s+ги\s+(претходните|инструкциите|горните)|"
    r"заборави\s+ги\s+претходните|системски\s+промпт)"
)


class RateLimiter:
    """Sliding-window лимитер по клуч (IP). Thread-safe, in-memory."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        sega = time.monotonic()
        with self._lock:
            vremenski_zapisi = self._hits[key]
            while vremenski_zapisi and sega - vremenski_zapisi[0] > self.window:
                vremenski_zapisi.popleft()
            if len(vremenski_zapisi) >= self.limit:
                return False
            vremenski_zapisi.append(sega)
            # спречи неограничен раст на мапата
            if len(self._hits) > 10_000:
                zastareni = [kluc for kluc, pogodoci in self._hits.items() if not pogodoci]
                for kluc in zastareni:
                    del self._hits[kluc]
            return True


class RedisRateLimiter:
    """Fixed-window лимитер во Redis — споделен меѓу процеси.

    Fail-open: ако Redis падне, пропуштаме (достапноста > строгост),
    а грешката се логира.
    """

    def __init__(self, url: str, limit: int, window_seconds: int = 60) -> None:
        import redis  # опционална зависност — само со REDIS_URL

        self.limit = limit
        self.window = window_seconds
        self._r = redis.Redis.from_url(url, decode_responses=True,
                                       socket_timeout=2)

    def allow(self, key: str) -> bool:
        try:
            redis_kluc = f"rl:{key}"
            pipe = self._r.pipeline()
            pipe.incr(redis_kluc)
            pipe.expire(redis_kluc, self.window, nx=True)
            brojac, _ = pipe.execute()
            return int(brojac) <= self.limit
        except Exception as greshka:  # noqa: BLE001
            logger.warning("Redis rate limit недостапен (%s) — fail-open", greshka)
            return True


def _make_limiter(limit: int):
    if settings.redis_url:
        return RedisRateLimiter(settings.redis_url, limit=limit)
    return RateLimiter(limit=limit)


session_rate_limiter = _make_limiter(settings.rate_limit)
ip_rate_limiter = _make_limiter(settings.rate_limit_ip)


def verify_api_key(provided: str | None) -> bool:
    """True ако API key не е конфигуриран, или ако се совпаѓа (constant-time)."""
    if not settings.api_access_key:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, settings.api_access_key)


def sanitize_question(raw: str) -> tuple[str, bool]:
    """Исчисти прашање: контролни карактери, должина, injection фрази.

    Враќа (чисто_прашање, injection_детектиран).
    """
    prashanje = _CONTROL_RE.sub("", raw or "")
    prashanje = re.sub(r"\s+", " ", prashanje).strip()
    prashanje = prashanje[: settings.max_question_chars]
    oznaceno = bool(_INJECTION_RE.search(prashanje))
    if oznaceno:
        prashanje = _INJECTION_RE.sub("[отстрането]", prashanje)
    return prashanje, oznaceno
