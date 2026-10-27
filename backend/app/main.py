# FastAPI vlezna tocka: CORS, limiti, observability, warmup, health/ready/metrics.
# Chat ruterot e vo app.api.chat; Qdrant/modeli se zagrevaat vo lifespan.
from __future__ import annotations
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router as chat_router
from app.config import settings
from app.core import rerank, vectorstore
from app.observability import Timer, metrics, request_id_var, setup_logging
from app.security import verify_api_key

setup_logging()
logger = logging.getLogger(__name__)

def _warmup() -> None:
    """Vcitaj dense/sparse/rerank pri start — prviot student da ne ceka download."""
    try:
        list(vectorstore._get_dense().embed(["query: загревање"]))
        if settings.use_hybrid:
            list(vectorstore._get_sparse().embed(["загревање"]))
        rerank.rerank("загревање", ["документ за загревање"])
        logger.info("Моделите се вчитани (warmup)")
    except Exception as greshka:
        logger.warning("Warmup не успеа: %s", greshka)

def _qdrant_remote_unprotected() -> bool:
    """Daleku Qdrant bez API kluc = rizik; lokalni hostovi se OK."""
    host = (urlparse(settings.qdrant_url).hostname or "").lower()
    lokalni = {"localhost", "127.0.0.1", "::1", "qdrant"}
    return host not in lokalni and not settings.qdrant_api_key

@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Pri start: upozorenija za produkcija + warmup vo thread (da ne go blokira event loop)."""
    if settings.cors_origin_list:
        logger.info("Chat е отворен за CORS_ORIGINS (без клуч во виџетот). /metrics бара API_ACCESS_KEY.")
        if not settings.api_access_key:
            logger.warning("API_ACCESS_KEY не е поставен — /metrics е затворен.")
    else:
        logger.warning("CORS_ORIGINS не е поставен — browser барања нема да работат.")
        if not settings.api_access_key:
            logger.warning("API_ACCESS_KEY не е поставен — /chat е јавно достапен.")
    if not (settings.session_secret or settings.api_access_key):
        logger.warning("SESSION_SECRET не е поставен — session_id не е потпишан.")
    if not settings.redis_url:
        logger.warning("REDIS_URL не е поставен — за 2+ workers историјата и rate limit не се делат.")
    if not settings.trust_proxy_headers:
        logger.info("TRUST_PROXY_HEADERS=false. Зад load balancer стави true и TRUSTED_PROXY_HOPS.")
    if not settings.llm_max_calls_per_hour and not settings.llm_max_calls_per_day:
        logger.info("LLM буџет исклучен. За облак: LLM_MAX_CALLS_PER_HOUR и LLM_MAX_CALLS_PER_DAY.")
    if _qdrant_remote_unprotected():
        logger.warning("Qdrant URL не е локален и QDRANT_API_KEY недостасува.")
    await asyncio.to_thread(_warmup)
    yield

app = FastAPI(title="AskUGD", version="1.0.0",
              description="RAG асистент за студенти на УГД", lifespan=_lifespan)

_domeni = settings.cors_origin_list
if _domeni:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_domeni,
        allow_credentials="*" not in _domeni,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

# 64 KiB e dovolno za JSON chat; premnogu malo za base64 sliki (namerno — nema upload).
_MAX_BODY_BYTES = 64 * 1024

@app.middleware("http")
async def body_size_limit(request: Request, call_next) -> Response:
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > _MAX_BODY_BYTES:
            return Response(
                content='{"detail":"Барањето е преголемо"}',
                status_code=413, media_type="application/json",
            )
    return await call_next(request)

@app.middleware("http")
async def observability_middleware(request: Request, call_next) -> Response:
    """Request-ID, latencija, metriki i bezbednosni response headeri."""
    id_baranje = uuid.uuid4().hex[:12]
    request_id_var.set(id_baranje)
    with Timer() as merac:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Необработена грешка")
            metrics.record(getattr(merac, "duration", 0.0), error=True)
            return Response(content='{"detail":"Внатрешна грешка"}',
                            status_code=500, media_type="application/json",
                            headers={"X-Request-ID": id_baranje})
    metrics.record(merac.duration, error=response.status_code >= 500)
    response.headers["X-Request-ID"] = id_baranje
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path,response.status_code, merac.duration * 1000)
    return response

app.include_router(chat_router)

@app.get("/health")
async def health() -> dict:
    """Liveness: procesot e ziv (ne proveruva Qdrant)."""
    return {"status": "ok"}

@app.get("/ready")
def ready() -> Response:
    """Readiness: Qdrant odgovara — Docker HEALTHCHECK / load balancer."""
    if vectorstore.ready():
        return Response(content='{"status":"ready"}', media_type="application/json")
    return Response(content='{"status":"not ready"}', status_code=503, media_type="application/json")

@app.get("/metrics")
async def get_metrics(request: Request) -> dict:
    """Latencija + kes statistika — samo so validen X-API-Key."""
    if not settings.api_access_key:
        raise HTTPException(status_code=403, detail="Metrics се затворени: постави API_ACCESS_KEY")
    if not verify_api_key(request.headers.get("x-api-key")):
        raise HTTPException(status_code=401, detail="Невалиден API клуч")
    from app.core.cache import answer_cache
    return {**metrics.snapshot(), **answer_cache.stats()}
