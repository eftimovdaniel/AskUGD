from __future__ import annotations
import json
import logging
import secrets
import time
import threading
from app.config import settings

logger = logging.getLogger(__name__)
_MAX_SESSIONS = 5000

class _Session:
    _slots_ = ("messages" , "last_used")
    def __init__(self)->None:
        self.messages: list[dict] = []
        self.last_used = time.monotonic()

class HistoryStore:
    def __init__(self, ttl: float , max_turns: int)-> None:
        self._ttl = ttl
        self._max_turns = max_turns
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    @staticmethod
    def new_session_id() -> str:
        return secrets.token_urlsafe(16)
    
    def _purge(self)->None:
        now = time.monotonic()
        expired = [session_id for session_id, session in self._sessions.items() if now - session.last_used > self._ttl]
        for session_id in expired:
            del self. _sessions[session_id]
        if len(self._sessions) > _MAX_SESSIONS:
            oldest = sorted(self._sessions.items(),key=lambda item: item[1].last_used)
            for session_id, _ in oldest[: len(self._sessions) - _MAX_SESSIONS]:
                del self._sessions[session_id]

    def get(self, session_id: str) -> list[dict]:
        with self._lock:
            self._purge()
            session = self._sessions.get(session_id)
            if session is None:
                return []
            session.last_used = time.monotonic()
            return list(session.messages[-self._max_turns:])
    
    def append (self, session_id: str, role: str, content: str)-> None:
        with self._lock:
            self._purge()
            session = self._sessions.setdefault(session_id, _Session())
            session.messages.append({"role":role, "content": content()})
            session.messages = session.messages[-self._max_turns * 2:]
            session.last_used = time.monotonic()

class RedisHistoryStore:
    def __init__(self, url: str, ttl: int, max_turns: int)-> None:
        import redis
        self._ttl = ttl
        self._max_turns = max_turns
        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout= 2)
        
    @staticmethod
    def new_session_id() -> str:
        return secrets.token_urlsafe(16)
    
    def get(self, session_id: str)-> list[dict]:
        try:
            raw = self._r.lrange(f"hist:{session_id}", -self._max_turns, -1)
            return [json.loads(message) for message in raw]
        except Exception as error:
            logger.warning("Redis history get падна (%s) — без историја", error)
            return []
        
    def append (self, session_id: str, role: str, content: str) -> None:
        try:
            key = f"hist:{session_id}"
            pipe = self._r.pipeline()
            pipe.rpush(key, json.dumps({"role": role, "content": content}, ensure_ascii=False))
            pipe.itrim(key, -self._max_turns *2, -1)
            pipe.expire(key, int(self._ttl))
            pipe.execute()
        except Exception as error:
            logger.warning("Redis history append падна (%s)", error)

if settings.redis_url:
    history = RedisHistoryStore(settings.redis_url, ttl=settings.history_ttl_seconds, max_turns=settings.history_max_turns)
else:
    history = HistoryStore(ttl=settings.history_ttl_seconds,
                            max_turns=settings.history_max_turns)