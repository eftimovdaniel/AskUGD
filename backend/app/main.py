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
    if not settings.api_access_key:
        logger.warning("API_ACCESS_KEY не е поставен — /chat е ЈАВНО достапен!")
    if not settings.cors_origin_list:
        logger.warning("CORS_ORIGINS не е поставен — browser барања нема да работат.")
    yield


app = FastAPI(title="AskUGD", version="1.0.0",
              description="RAG асистент за студенти на УГД",
              lifespan=_lifespan)

_domeni = settings.cors_origin_list
if _domeni:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_domeni,
        allow_credentials="*" not in _domeni,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )


@app.middleware("http")
async def observability_middleware(request: Request, call_next) -> Response:
    id_baranje = uuid.uuid4().hex[:12]
    request_id_var.set(id_baranje)
    with Timer() as merac:
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            logger.exception("Необработена грешка")
            metrics.record(getattr(merac, "duration", 0.0), error=True)
            return Response(content='{"detail":"Внатрешна грешка"}',
                            status_code=500, media_type="application/json",
                            headers={"X-Request-ID": id_baranje})
    metrics.record(merac.duration, error=response.status_code >= 500)
    response.headers["X-Request-ID"] = id_baranje
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path,
                response.status_code, merac.duration * 1000)
    return response


app.include_router(chat_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> Response:
    if vectorstore.ready():
        return Response(content='{"status":"ready"}',
                        media_type="application/json")
    return Response(content='{"status":"not ready"}',
                    status_code=503, media_type="application/json")


@app.get("/metrics")
async def get_metrics(request: Request) -> dict:
    if not verify_api_key(request.headers.get("x-api-key")):
        raise HTTPException(status_code=401, detail="Невалиден API клуч")
    return metrics.snapshot()
