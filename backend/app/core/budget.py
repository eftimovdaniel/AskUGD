# Globalen kap na LLM povici (sat / den). 0 = iskluceno.
# So Redis se deli megju workers; bez Redis e per-process (slabije, no ne unlimited).
from __future__ import annotations
import logging
import threading
import time
from app.config import settings

logger = logging.getLogger(__name__)

BUDGET_MSG = "Сервисот е привремено преоптоварен. Обиди се подоцна."

class LlmBudgetExceeded(Exception):
    pass

class InMemoryLlmBudget:
    def __init__(self, hour_limit: int, day_limit: int) -> None:
        self.hour_limit = hour_limit
        self.day_limit = day_limit
        self._lock = threading.Lock()
        self._hour_key = ""
        self._hour_n = 0
        self._day_key = ""
        self._day_n = 0

    def try_consume(self) -> bool:
        if not self.hour_limit and not self.day_limit:
            return True
        sega = time.gmtime()
        hour_key = time.strftime("%Y%m%d%H", sega)
        day_key = time.strftime("%Y%m%d", sega)
        with self._lock:
            if hour_key != self._hour_key:
                self._hour_key = hour_key
                self._hour_n = 0
            if day_key != self._day_key:
                self._day_key = day_key
                self._day_n = 0
            if self.hour_limit and self._hour_n >= self.hour_limit:
                return False
            if self.day_limit and self._day_n >= self.day_limit:
                return False
            self._hour_n += 1
            self._day_n += 1
            return True


class RedisLlmBudget:
    def __init__(self, url: str, hour_limit: int, day_limit: int) -> None:
        import redis
        self.hour_limit = hour_limit
        self.day_limit = day_limit
        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
        self._fallback = InMemoryLlmBudget(hour_limit, day_limit)

    def try_consume(self) -> bool:
        if not self.hour_limit and not self.day_limit:
            return True
        try:
            sega = time.gmtime()
            hour_key = time.strftime("llm:h:%Y%m%d%H", sega)
            day_key = time.strftime("llm:d:%Y%m%d", sega)
            pipe = self._r.pipeline()
            if self.hour_limit:
                pipe.incr(hour_key)
                pipe.expire(hour_key, 3700, nx=True)
            if self.day_limit:
                pipe.incr(day_key)
                pipe.expire(day_key, 90000, nx=True)
            rezultati = pipe.execute()
            indeks = 0
            if self.hour_limit:
                broj = int(rezultati[indeks])
                indeks += 2
                if broj > self.hour_limit:
                    return False
            if self.day_limit:
                broj = int(rezultati[indeks])
                if broj > self.day_limit:
                    return False
            return True
        except Exception as greshka:
            logger.warning("Redis LLM буџет недостапен (%s) — fallback на in-memory", greshka)
            return self._fallback.try_consume()

def _make_budget() -> InMemoryLlmBudget | RedisLlmBudget:
    hour = settings.llm_max_calls_per_hour
    day = settings.llm_max_calls_per_day
    if settings.redis_url:
        return RedisLlmBudget(settings.redis_url, hour, day)
    return InMemoryLlmBudget(hour, day)

llm_budget = _make_budget()

def consume_llm() -> None:
    if not llm_budget.try_consume():
        raise LlmBudgetExceeded(BUDGET_MSG)
