from __future__ import annotations
import json
import logging
import secrets
import threading
import time
from app.config import settings

logger = logging.getLogger(__name__)
_MAX_SESSIONS = 5000 # limit, max 5000 sesii vo memorija, zastita od iscrapuvanje na ram vo pikot na baranjeto

class _Session: # vnatresnata klasa za edna sesija, 
    __slots__ = ("messages", "last_used")   # gi fiksira dozvolenite atributi, so toa se trose pomalku memorija korisno koga ima iljadnici sesii
    def __init__(self) -> None: # konstruktor
        self.messages: list[dict] = [] # prazna lista poraki za ovaa sesija
        self.last_used = time.monotonic()  # vreme na sozdavanje

class HistoryStore: # in memory sklad za istorija 
    def __init__(self, ttl: float, max_turns: int) -> None: # ttl kolku dolgo zivee sesijata, max_turns kolku poraki da se zapamtat
        self._ttl = ttl # se zacuvuva vo ttl vo sekundi
        self._max_turns = max_turns # kolku posledno poraki se vrakaat kako kontekst
        self._sessions: dict[str, _Session] = {}  #session_id go dava vo Session objekti, bazata vo memorijata
        self._lock = threading.Lock()   

    @staticmethod  # staticki metod, ne treba self
    def new_session_id() -> str:    # definira nov unikaten session_id 
        return secrets.token_urlsafe(16)    # urlsafe so 16 slucajni bajti, kodnirani url bezbedno

    def _purge(self) -> None: # cisti isteceni sesii
        sega = time.monotonic() # tekovnoto vreme
        isteceni = [session_id for session_id, sesija in self._sessions.items() # se baraat sesiite sto ne se koristeni podolgo od ttl
                   if sega - sesija.last_used > self._ttl]  # uslovot e da e pominalo poveke vreme od ttl od poseldnata upotreba
        for session_id in isteceni: # za sekoja istecena sesija
            del self._sessions[session_id]  # se brise i se osloboduva memorija za naredna sesija
        # хард лимит против мемориска исцрпеност
        if len(self._sessions) > _MAX_SESSIONS: # dokolku pri cistenjeto ima mnogu sesii 
            najstari = sorted(self._sessions.items(),key=lambda element: element[1].last_used) # se sortiraat po vremeot na posledna upotreba
            for session_id, _ in najstari[: len(self._sessions) - _MAX_SESSIONS]: # se zemaat najstarite nad limitor i se prisat
                del self._sessions[session_id]  # se birsta site so se podredeni od gorniot uslov, a so toa sekogas imame po 5000 aktivni sesii

    def get(self, session_id: str) -> list[dict]:  #se vraka poslednite poraki za dadena sesija
        with self._lock:   #zakluci thread-safe cistenje so avtomatsko otklucuvanje na kraj
            self._purge()  
            sesija = self._sessions.get(session_id) # se bara sesijata 
            if sesija is None:  # dokolku e nova sesoka ili ustata e nepoznata 
                return []   # se vraka prazna istorija
            sesija.last_used = time.monotonic() # update na sesijata, sesijata e aktivna od ovoj moment da ne se stave kraj na sesijata koja sega zapocnuva
            return list(sesija.messages[-self._max_turns:]) # se vraka posledniot max_turns poraka, list pravi kopija za da ne se menuva orginalot odnadvpr

    def append(self, session_id: str, role: str, content: str) -> None:  # dodavanje na nova poraka vo sesijata
        with self._lock:
            self._purge()
            sesija = self._sessions.setdefault(session_id, _Session()) # se zima sesijata  ili se sozdava nova ako ne postoi
            sesija.messages.append({"role": role, "content": content}) # dodadi ja porakata 
            sesija.messages = sesija.messages[-self._max_turns * 2:]  # se zema poslednite max_turns * 2 poraki *2: eden „turn" e prasanje + odgovor (2 poraki),pa pamti max_turns razmeni.
            sesija.last_used = time.monotonic() # se update vremeto

class RedisHistoryStore:
    def __init__(self, url: str, ttl: int, max_turns: int) -> None:
        import redis  # опционална зависност — само со REDIS_URL
        self._ttl = ttl # ttl za isteknuvanje na klucevite vo Redis
        self._max_turns = max_turns # definira kolku poraki da se pamtat
        self._r = redis.Redis.from_url(url, decode_responses=True,socket_timeout=2)

    @staticmethod
    def new_session_id() -> str:    # generira session_id 
        return secrets.token_urlsafe(16)

    def get(self, session_id: str) -> list[dict]:  # vraka istorija od Redis
        try: # obidi se redis moze da padne 
            surovo = self._r.lrange(f"hist:{session_id}", -self._max_turns, -1) # lrange gi vraka poslednite max_turns elementi od lista. 
            return [json.loads(poraka) for poraka in surovo]    # sekoja poraka e json string - se pretvara nazad vo recnik
        except Exception as greshka:  # dokolku Redis padne
            logger.warning("Redis history get падна (%s) — без историја", greshka)
            return [] # se prodolzuva bez istorija

    def append(self, session_id: str, role: str, content: str) -> None: # dodavanje poraki vo redis
        try:
            kluc = f"hist:{session_id}" # kluc za ovaa sesija
            pipe = self._r.pipeline()   # so pipeline se grupiraat poceke komandi i se prakaat oddednas, podbro za obrabotka
            pipe.rpush(kluc, json.dumps({"role": role, "content": content},ensure_ascii=False)) #rpush se dodava na kraj na listata. Porakite se pretvaraat vo json string
            pipe.ltrim(kluc, -self._max_turns * 2, -1) #ltrim( zadrzi samo poslednite max_turn *2 elementi
            pipe.expire(kluc, int(self._ttl)) #expire se postaviva isteknuvanje na klucot, redis sam go prise ttl ne treba da se racno ciste
            pipe.execute()  # se izvrsuvaat site komandi odednas
        except Exception as greshka:  # dokolku imame pad na redis
            logger.warning("Redis history append падна (%s)", greshka)
if settings.redis_url:  # na vcituvanje na modulot, ako redis_url e postaven vo env
    history = RedisHistoryStore(settings.redis_url,ttl=settings.history_ttl_seconds, max_turns=settings.history_max_turns)
else:   #inaku
    history = HistoryStore(ttl=settings.history_ttl_seconds, max_turns=settings.history_max_turns)
