from __future__ import annotations
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.config import settings
from app.core.generator import generate, stream_generate
from app.core.history import history
from app.core.retriever import RetrievalUnavailable, extract_sources, retrieve
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.security import (ip_rate_limiter, sanitize_question,
                          session_rate_limiter, verify_api_key)

logger = logging.getLogger(__name__)
router = APIRouter()

NO_INFO_MSG = ("Немам информација за тоа во достапната документација. "
               "Обрати се до Студентска служба на УГД за помош.")
GENERIC_ERROR = "Настана грешка при обработката. Обиди се повторно."


def _client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        prosleden = request.headers.get("x-forwarded-for")
        if prosleden:
            return prosleden.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def guard(req: ChatRequest, request: Request) -> None:
    if not verify_api_key(request.headers.get("x-api-key")):
        raise HTTPException(status_code=401, detail="Невалиден API клуч")
    ip_adresa = _client_ip(request)
    if not ip_rate_limiter.allow(f"ip:{ip_adresa}"):
        raise HTTPException(status_code=429,
                            detail="Премногу барања — обиди се за минута")
    kluc_sesija = req.session_id or ip_adresa
    if not session_rate_limiter.allow(f"s:{kluc_sesija}"):
        raise HTTPException(status_code=429,
                            detail="Премногу барања — обиди се за минута")


def _prepare(req: ChatRequest) -> tuple[str, str, list[dict], list[dict]]:
    prashanje, oznaceno = sanitize_question(req.question)
    if oznaceno:
        logger.warning("Injection обид детектиран во прашање")
    if not prashanje:
        raise HTTPException(status_code=422, detail="Празно прашање")

    session_id = req.session_id or history.new_session_id()
    prethodni_poraki = history.get(session_id)
    try:
        parchinja = retrieve(prashanje)
    except RetrievalUnavailable:
        logger.exception("Retrieval недостапен")
        raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None
    return prashanje, session_id, prethodni_poraki, parchinja


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, _=Depends(guard)) -> ChatResponse:
    prashanje, session_id, prethodni_poraki, parchinja = _prepare(req)

    if not parchinja:
        odgovor = NO_INFO_MSG
    else:
        try:
            odgovor = generate(prashanje, parchinja, prethodni_poraki)
        except Exception:  # noqa: BLE001
            logger.exception("Генерацијата падна")
            raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None

    history.append(session_id, "user", prashanje)
    history.append(session_id, "assistant", odgovor)
    return ChatResponse(
        answer=odgovor,
        sources=[Source(**izvor) for izvor in extract_sources(parchinja)],
        session_id=session_id,
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request, _=Depends(guard)):
    prashanje, session_id, prethodni_poraki, parchinja = _prepare(req)

    def event(podatoci: dict) -> str:
        return f"data: {json.dumps(podatoci, ensure_ascii=False)}\n\n"

    def stream():
        yield event({"type": "sources", "sources": extract_sources(parchinja),
                     "session_id": session_id})
        delovi_odgovor: list[str] = []
        try:
            if not parchinja:
                delovi_odgovor.append(NO_INFO_MSG)
                yield event({"type": "token", "token": NO_INFO_MSG})
            else:
                for token in stream_generate(prashanje, parchinja, prethodni_poraki):
                    delovi_odgovor.append(token)
                    yield event({"type": "token", "token": token})
        except Exception:  # noqa: BLE001
            logger.exception("Streaming генерацијата падна")
            yield event({"type": "error", "message": GENERIC_ERROR})
            return
        history.append(session_id, "user", prashanje)
        history.append(session_id, "assistant", "".join(delovi_odgovor))
        yield event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream",headers={"Cache-Control": "no-cache","X-Accel-Buffering": "no"})
