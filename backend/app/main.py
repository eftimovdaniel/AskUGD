from __future__ import annotations
import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.config import settings
from app.core import vectorstore
from app.observability import Timer, metrics, request_id_var, setup_logging
from app.security import verify_api_key

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI):  
    if not settings.api_access_key: #proverka dali api key e postaven ili ne 
        logger.warning("API_ACCESS_KEY не е поставен — /chat е ЈАВНО достапен!")    #vo log vraka poraka za greska
    if not settings.cors_origin_list:   #ako cors ne postoi
        logger.warning("CORS_ORIGINS не е поставен — browser барања нема да работат.")  #predupreduvanje vo log
    yield # orabotka na baranjata, kodot pred nego e star a posle e za gasnenje

app = FastAPI(title="AskUGD", version="1.0.0",  #sozdavanje na fastapi aplikacija so naslov i verzija, objasnuvanje i lifespan
              description="RAG асистент за студенти на УГД",    
              lifespan=_lifespan)

_domeni = settings.cors_origin_list # zamenuvanje na dozvoleni domeni od env vo cors
if _domeni: #dokolku se postaveni
    app.add_middleware( # dodavam cors middleware
        CORSMiddleware,
        allow_origins=_domeni,  # domeni koj smejta da pratat baranje
        allow_credentials="*" not in _domeni,   #dozvoluvanje na kolacija
        allow_methods=["GET", "POST"],  # samo get i post metodi ni se dozvoleni
        allow_headers=["Content-Type", "X-API-Key"],    #koi headers smee da gi prati kliento
    )

@app.middleware("http") #middleweate kod sto se izvrasuva okolu sekoe baranje 
async def observability_middleware(request: Request, call_next) -> Response:   #dojdoven request, call_next funkcija sto go izvrasuva vistinskiot endpoint
    id_baranje = uuid.uuid4().hex[:12] #generiranje na unikaten id na request za sledenje 
    request_id_var.set(id_baranje)  #postavuvanje vo contextvar, site baranja avtomatski go nosta ovoj id 
    with Timer() as merac:  #pocetok na merenje na vremeto, timer avtomatski go presmetuva vremetraenjeto na izlez od blokot
        try:    #obid za obrabokata na baranjeto
            response = await call_next(request) # izvrasuvanje an endpointos, mora da imam await bidejki middleware e async
        except Exception:  # ako nekade se sluci pad
            logger.exception("Необработена грешка")
            metrics.record(getattr(merac, "duration", 0.0), error=True) # zapisuvanje na greskata vo metrikite
            return Response(content='{"detail":"Внатрешна грешка"}',    # objasnuvanje 
                            status_code=500, media_type="application/json", #statusen kod na greskata
                            headers={"X-Request-ID": id_baranje})
    metrics.record(merac.duration, error=response.status_code >= 500)   # po obrabotka zapisuvame go vremetraenjeto, error = true ako statusto e 5XX
    response.headers["X-Request-ID"] = id_baranje   #dodavanje na request_id vo odgovorot
    response.headers["X-Content-Type-Options"] = "nosniff"# header za bezbednost sprecuvame da se pogoduva tip na sodrzina
    response.headers["Cache-Control"] = "no-store"  # ne go kesirame odgovorot, 
    logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path,response.status_code, merac.duration * 1000)
    return response #vrati go odgovorot na klientot

app.include_router(chat_router)

@app.get("/health") #liveness proverka dali prcesto e ziv
async def health() -> dict: 
    return {"status": "ok"} # dokolku imame odgovor se prikazuva deka serverot raboti

@app.get("/ready")  # proverka dali e ready da prima soobrakaj, baranja za obrabotka
def ready() -> Response:
    if vectorstore.ready(): #proverka dali bazata e spremna 
        return Response(content='{"status":"ready"}', media_type="application/json")    # dokolku e spremna vraka 200 ok 
    return Response(content='{"status":"not ready"}', status_code=503, media_type="application/json")   # dokolku ne e spremna vraka 503 

@app.get("/metrics")    #statistika 
async def get_metrics(request: Request) -> dict:   #prime request za da go proveri api klucot
    if not verify_api_key(request.headers.get("x-api-key")):   #zastita, metrikite na se javni
        raise HTTPException(status_code=401, detail="Невалиден API клуч")   #dokolku ne se pojavi validen api kluc
    return metrics.snapshot()   # vrakame tekovna statistika
