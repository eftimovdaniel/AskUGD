from __future__ import annotations
import json
import logging
import secrets
import threading
import time
from app.config import settings

logger = logging.getLogger(__name__)
_MAX_SESSIONS = 5000

class _Session:
    __slots__ = ("messages", "last_used")
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.last_used = time.monotonic()

class HistoryStore:
    def __init__(self, ttl: float, max_turns: int) -> None:
        self._ttl = ttl
        self._max_turns = max_turns
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    @staticmethod
    def new_session_id() -> str:
        return secrets.token_urlsafe(16)

    def _purge(self) -> None:
        sega = time.monotonic()
        isteceni = [session_id for session_id, sesija in self._sessions.items()
                   if sega - sesija.last_used > self._ttl]
        for session_id in isteceni:
            del self._sessions[session_id]
        # хард лимит против мемориска исцрпеност
        if len(self._sessions) > _MAX_SESSIONS:
            najstari = sorted(self._sessions.items(),
                            key=lambda element: element[1].last_used)
            for session_id, _ in najstari[: len(self._sessions) - _MAX_SESSIONS]:
                del self._sessions[session_id]

    def get(self, session_id: str) -> list[dict]:
        with self._lock:
            self._purge()
            sesija = self._sessions.get(session_id)
            if sesija is None:
                return []
            sesija.last_used = time.monotonic()
            return list(sesija.messages[-self._max_turns:])

    def append(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            self._purge()
            sesija = self._sessions.setdefault(session_id, _Session())
            sesija.messages.append({"role": role, "content": content})
            sesija.messages = sesija.messages[-self._max_turns * 2:]  # лимит
            sesija.last_used = time.monotonic()


class RedisHistoryStore:
    def __init__(self, url: str, ttl: int, max_turns: int) -> None:
        import redis  # опционална зависност — само со REDIS_URL

        self._ttl = ttl
        self._max_turns = max_turns
        self._r = redis.Redis.from_url(url, decode_responses=True,
                                       socket_timeout=2)

    @staticmethod
    def new_session_id() -> str:
        return secrets.token_urlsafe(16)

    def get(self, session_id: str) -> list[dict]:
        try:
            surovo = self._r.lrange(f"hist:{session_id}", -self._max_turns, -1)
            return [json.loads(poraka) for poraka in surovo]
        except Exception as greshka:  # noqa: BLE001
            logger.warning("Redis history get падна (%s) — без историја", greshka)
            return []

    def append(self, session_id: str, role: str, content: str) -> None:
        try:
            kluc = f"hist:{session_id}"
            pipe = self._r.pipeline()
            pipe.rpush(kluc, json.dumps({"role": role, "content": content},
                                       ensure_ascii=False))
            pipe.ltrim(kluc, -self._max_turns * 2, -1)
            pipe.expire(kluc, int(self._ttl))
            pipe.execute()
        except Exception as greshka:  # noqa: BLE001
            logger.warning("Redis history append падна (%s)", greshka)
if settings.redis_url:
    history = RedisHistoryStore(settings.redis_url,ttl=settings.history_ttl_seconds, max_turns=settings.history_max_turns)
else:
    history = HistoryStore(ttl=settings.history_ttl_seconds, max_turns=settings.history_max_turns)
