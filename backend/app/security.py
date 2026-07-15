from __future__ import annotations
import hmac
import logging
import re
import threading
import time 
from collections import defaultdict, deque
from app.config import settings

logger = logging.getLogger(__name__)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"disregard\s+(the\s+)?(above|previous|prior)|"
    r"you\s+are\s+now\b|act\s+as\s+(a|an)\b|new\s+instructions?\s*:|"
    r"system\s*prompt|developer\s+message|reveal\s+your\s+(instructions|prompt)|"
    r"игнорирај\s+ги\s+(претходните|инструкциите|горните)|"
    r"заборави\s+ги\s+претходните|системски\s+промпт)"
)

class RateLimiter:
    def __init__ (self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow (self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            timestamps = self._hits[key]
            while timestamps and now - timestamps[0] > self.window:
                timestamps.popleft()
            if len (timestamps) >= self.limit:
                return False
            timestamps.append(now)
            if len (self._hits)>10_000:
                stale = [map_key for map_key, hits in self._hits.items() if not hits]
                for map_key in stale:
                    del self._hits[map_key]
            return True

class RedisRateLimiter:
    def __init__(self, url: str, limit: int, window_seconds: int = 60) -> None:
        import redis
        self.limit = limit
        self.window = window_seconds
        self._r = redis.Redis.from_url(url, decode_responses = True, socket_timeout =2)

    def allow (self, key: str) -> bool:
        try:
            reis_key = f"rl:{key}"
            pipe = self._r.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, self.window, nx=True)
            count, _ = pipe.execute()
            return int(count) <= self.limit
        except Exception as error:  # noqa: BLE001
            logger.warning("Redis rate limit недостапен (%s) — fail-open", error)
            return True
        
def _make_limiter(limit:int):
    if settings.redis_url:
        return RedisRateLimiter(settings.redise_url, limit = limit)
    return RateLimiter (limit = limit)

session_rate_limiter = _make_limiter(settings.rate_limit)
ip_rate_limiter = _make_limiter(settings.rate_limit_ip)

def verify_api_key(provided: str | None) -> bool:
    if not settings.api_access_key:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, settings.api_access_key)

def sanitize_question(raw: str) -> tuple[str, bool]:
    question = _CONTROL_RE.sub("", raw or "")
    question = re.sub(r"\s+", " ", question).strip()
    question = question[: settings.max_question_chars]
    flagged = bool(_INJECTION_RE.search(question))
    if flagged:
        question = _INJECTION_RE.sub("[отстрането]", question)
    return question, flagged
