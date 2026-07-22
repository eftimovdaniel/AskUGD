from __future__ import annotations
import hmac
import logging
import re
import threading
import time
from collections import defaultdict, deque
from app.config import settings

logger = logging.getLogger(__name__)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  #Regez za kontrolni karakteri osven \n i \t , se brisat za da ne se rasipat logovite

_INJECTION_RE = re.compile( #Regex za najcesti promt injection frazi so prasanje, ako se napise ignore all instructions od strana na korisnikot go faka i go neutralizira 
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"disregard\s+(the\s+)?(above|previous|prior)|"
    r"you\s+are\s+sega\b|act\s+as\s+(a|an)\b|new\s+instructions?\s*:|"
    r"system\s*prompt|developer\s+message|reveal\s+your\s+(instructions|prompt)|"
    r"игнорирај\s+ги\s+(претходните|инструкциите|горните)|"
    r"заборави\s+ги\s+претходните|системски\s+промпт)"
)

class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None: #limit = kolki baranje se dozvoleni a so window. = vo kolkav prozorec 
        self.limit = limit  
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)    #za sekoj kluc (IP/sesija) redica od vreminja na baranje, defaultdict(deque) se dobiva prazna redica 
        self._lock = threading.Lock()   #lock, serverot obrabotuva poveke baranja, bez lock dve nitki moze da ja rasipat redicata

    def allow(self, key: str) -> bool:  # vraka true ili false
        sega = time.monotonic() # tekovnoto vreme 
        with self._lock:    #
            vremenski_zapisi = self._hits[key]  # redica od vreminjata za ovoj kluc
            while vremenski_zapisi and sega - vremenski_zapisi[0] > self.window:    # se otstranuvaat starite baranja
                vremenski_zapisi.popleft()  # so popleft se brise najstarot
            if len(vremenski_zapisi) >= self.limit: #ako vo prozorecot go imame veke limitot
                return False    # se odbiva
            vremenski_zapisi.append(sega)   #inaku se zapisuva ova baranje
            if len(self._hits) > 10_000:    # dokolki ima premnogu klucevi, razlicni ip adresi 
                zastareni = [kluc for kluc, pogodoci in self._hits.items() if not pogodoci] # se naogaat praznite redici 
                for kluc in zastareni:  #i se brisat istite a so toa osloboduvame memorija
                    del self._hits[kluc]
            return True

class RedisRateLimiter:
    def __init__(self, url: str, limit: int, window_seconds: int = 60) -> None:
        import redis  
        self.limit = limit
        self.window = window_seconds
        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)

    def allow(self, key: str) -> bool:  #insti interfejs kako in memory
        try:
            redis_kluc = f"rl:{key}"    # kluc vo redis 
            pipe = self._r.pipeline()   # pipline grupirani komandi za da se pratat na ednas i so toa e pobrzo
            pipe.incr(redis_kluc)   #incr gp zolemuvame brojacot za 1
            pipe.expire(redis_kluc, self.window, nx=True)     #expire nx=true postavuva istekuvanje samo ako veke nema 
            brojac, _ = pipe.execute()  # izvrsuvame gi dvete, se zema rezultatot od incr 
            return int(brojac) <= self.limit    # se dozvoluva ako brojacot e pod limit
        except Exception as greshka:  # dokolku imame pad od redis
            logger.warning("Redis rate limit недостапен (%s) — fail-open", greshka)
            return True # dozvoluva, se pusta baranje = podobro, namesto da padne celiot servis

def _make_limiter(limit: int):  #izbira redis ili in memory spored konfiguracijata
    if settings.redis_url:  # dokolku redis_url e postaven
        return RedisRateLimiter(settings.redis_url, limit=limit)  #redis verzija (za poveke workers)
    return RateLimiter(limit=limit) #inaku in memory (dozvolen e samo eden worker)
session_rate_limiter = _make_limiter(settings.rate_limit) # limiter po sesija, se vika vo guard()
ip_rate_limiter = _make_limiter(settings.rate_limit_ip) # limiter po ip 

def verify_api_key(provided: str | None) -> bool:   # proveruva api klucevi, 
    if not settings.api_access_key: #dokolku klucot ne e konfiguriran
        return True # dozvoli 
    if not provided:    # dokolki e konfiguriran no klientot ne pratil kluc 
        return False     # se odbiva
    return hmac.compare_digest(provided, settings.api_access_key)   # sporedba 

def sanitize_question(raw: str) -> tuple[str, bool]:    #go cisti prasanjeto, vraka cisto prasanje, dali ima detektirano injection...
    prashanje = _CONTROL_RE.sub("", raw or "")  # se trgaat kontrolnite znaci
    prashanje = re.sub(r"\s+", " ", prashanje).strip()  #povekekratni mesta = edno , se cistat kraevite
    prashanje = prashanje[: settings.max_question_chars]    # se krati na max dolzina, so toa se prave zastota d ogromni prasanja, i se cuvaat tokeni
    oznaceno = bool(_INJECTION_RE.search(prashanje))    # se proveruva dali ima injection frazi, so bool se vraka true ili false
    if oznaceno:   # dokolku e detektirana
        prashanje = _INJECTION_RE.sub("[отстрането]", prashanje)    # se zamenuva frazata so [otstraneto], neutralizacija no ne go otfrlame celot prasanje
    return prashanje, oznaceno  # se vraka iscistenoto prasanje i znamence
