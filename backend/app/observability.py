from __future__ import annotations
import contextvars
import json
import logging
import threading
import time

#promenliva stp civa razlicni vrednost za sekoe baranje. ContextVar garantira ddeka sekoj go gleda svojot request id bez da bidat izmesani, a defailt e koga nema aktivni baranja
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class JsonFormatter(logging.Formatter): #logot se pretvara vo json objekt
    def format (self, record: logging.LogRecord) -> str:    #logging ja povikuva sekoja log poraka, record go nosi site podatoci
        entry = { # recnik sto se se pretvori vo json
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),   # vremenska oznaka vo iso standard
            "level": record.levelname,  #nivo dali stanuva zbor za error warning
            "logger": record.name,  # koj modul go sozdava
            "request_id": request_id_var.get(), # request id na tekovnoto baranje
            "msg":record.getMessage(),  # porakata
        }
        if record.exc_info: #dokolku logot e od greska so trackback 
            entry["exc"] = self.formatException(record.exc_info)    # se dodava celiot trackback kako posebno pole
        return json.dumps(entry, ensure_ascii=False)    # recenica ja pretvarame vo json tekst, ensute_ascii ja cuva kirilicata citliva
    
def setup_logging (level: int = logging.INFO) -> None:  
    handler = logging.StreamHandler()   # nandler sto pisuva vo konzolata 
    handler.setFormatter(JsonFormatter())   # se definira deka ke se koristi json format
    root = logging.getLogger()    #se zema root loggerot
    root.handlers = [handler]   # se zemaat site handlers i se zamenuvaat so nasiot 
    root.setLevel(level)    #debug poraka
    logging.getLogger("uvicorn.access").disabled = True 

class Metrics:  #broenje na greski baranja prosecna latencija ... 
    def __init__(self) -> None:
        self._lock = threading.Lock()   #broenjeto mora e thread safe 
        self.requests = 0   # vkupen broj na obraboteni baranja
        self.errors = 0 # Vkupen broj na baranja sto zavrsile so greska 
        self._latency_sum = 0.0 #zbir na vremetranjeto na site baranja

    def record (self, duration_s: float, error: bool = False) -> None:  #zapisuvanje na edno baranje, se vika po sekoe baranje, kolku traelo i dali bilo greska
        with self._lock:    # zakluci dodeka menuvame, avtomatsko otklucivanje na kraj
            self.requests += 1  #zbolemuvanje na brojot na baranj za 1 
            self._latency_sum += duration_s #dodavanje na vremetraenjeto na ova baranje vo vkupnoto vreme na site baranja
            if error:  #dokolku se javi baranje so error/greska
                self.errors +=1 #se zgolemuva brojacot za greski
    
    def snapshot(self)->dict:   #vraka tekovna slika od statistikata kako recnik.
        with self._lock:    #zakluceno e dodeka se cita
            avg = self._latency_sum / self.requests if self.requests else 0.0   #prosecnata latencija = vkupnio zbor / broj na baranja vo daden moment
            return{ #se vrakaat site 3 metriki
                "requests": self.requests,  #vkupen broj baranja
                "errors": self.errors,  #greski
                "avg_latency_ms": round(avg * 1000, 1), # prosecna latentnost, se presmetuva vo ms
            }
metrics = Metrics() #sozdavanje na edna globalna instanca. Site se zapisuvaat vo eden ist brojac

class Timer:   #merac na vremetraenjeto
    def __enter__(self) -> "Timer": # specijalen metod vo python ja vika na vlez, vraka timer 
        self.start = time.perf_counter()   #zapisuvame go momentot na start. 
        return self 
    def __exit__(self, *exc) -> None:   # specijalen metod vo python ja vika na vlez od with blok, sekogas duri i ako sreden blok padne 
        self.duration = time.perf_counter() - self.start    # se presmetuva vremetraenjeto : tekovniot moment - stariot moment 