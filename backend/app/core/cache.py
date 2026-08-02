#In-memory kes za gotovi odgovori — isto prasanje (bez istorija) se vraka od kes bez nov LLM povik. 
#TTL (istekuvanje) + LRU (frla najstaro) + thread-safe. 
#normalize_key pravi isto prasanje so razlicni praznini/bukvi da e ist kluc.
from __future__ import annotations
import re
import threading
import time
from collections import OrderedDict
from typing import Any
from app.config import settings

_WS_RE = re.compile(r"\s+") #regez za dve ili poveke praznini

def normalize_key(question: str) -> str:    #kriranje kluc na prasanjeto
    return _WS_RE.sub(" ", question).strip().lower()  #poveke praznini, se trgaat vo edno, trganje na kraevite i mali bukvi

class AnswerCache:  #kesh za gotovite odgovori, onie koa veke gi ima nekoj postavveno
    def __init__(self, max_size: int, ttl_seconds: float) -> None:  #konstrukutor 
        self._max = max_size    #max broj zapisi 
        self._ttl = ttl_seconds #max vreme na ziveenje vo sekundi 
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()  #kluc
        self._lock = threading.Lock()    #lock protiv dve nitki da ja rasipat strukturata
        self.hits = 0   #brojac za vo kesh dokolku e pronajdeno
        self.misses = 0 #brojac, dokolku ne e pronajdeno vo kesh

    def get(self, key: str) -> Any: #zemi zapisi od kesot 
        sega = time.monotonic() #tekovno vreme 
        with self._lock:    #zakluci dodeka citame
            zapis = self._store.get(key)    #proba da se pronajde klucot 
            if zapis is None:   #dokolku go nema voopsto
                self.misses += 1    #zabelezano e poramnuvanje
                return None #ne vrati nisto
            vreme, vrednost = zapis #raspakuvanje (koga e zapisot, odgovorot)
            if sega - vreme > self._ttl:    #ako e istecen
                del self._store[key]    #frli go
                self.misses += 1    #smetaj go kako promasuvanje 
                return None    #ne vrakaj nisto
            self._store.move_to_end(key)   # svez pristap -> pomesti na kraj  
            self.hits += 1  #se stava deka e zabelezano pogoduvanje s
            return vrednost #vrakanje na zacuvan odgovor 

    def set(self, key: str, value: Any) -> None:    #zapis na nov odovor vo keshot 
        sega = time.monotonic() #tekovno vreme na zapis
        with self._lock:    #zakluci dodeka zapisuvame
            self._store[key] = (sega, value)    #zapis pod klucot 
            self._store.move_to_end(key)    #pomestuvanje na kraj
            while len(self._store) > self._max: #ako se nadmine limitot
                self._store.popitem(last=False) #se dava najstaroto

    def clear(self) -> None:    #praznenje na celiot kesh
        with self._lock:    
            self._store.clear() #brisenje na site podatoci

    def stats(self) -> dict:    #vrakjanje na statistika za keshot
        with self._lock:    #zaklucuvanje dodeka se cita 
            vkupno = self.hits + self.misses    #vkupen broj baranja niz keshot
            return {
                "cache_size": len(self._store),
                "cache_hits": self.hits,
                "cache_misses": self.misses,
                "cache_hit_rate": round(self.hits / vkupno, 3) if vkupno else 0.0,
            }

answer_cache = AnswerCache( #globalna istanca na keshot za gotovite odgovori
    max_size=settings.cache_max_size,   #limit 
    ttl_seconds=settings.cache_ttl_seconds, #TTL 
)
