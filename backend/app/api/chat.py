from __future__ import annotations
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.config import settings
from app.core.generator import generate, stream_generate
from app.core.history import history
from app.core.retriever import  RetrievalUnavailable, extract_sources, retrieve
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.security import (ip_rate_limiter, sanitize_question, session_rate_limiter, verify_api_key)

logger = logging.getLogger(__name__)
router = APIRouter()
NO_INFO_MSG = ("Немам информација за тоа во достапната документација. "
               "Обрати се до Студентска служба на УГД за помош.")
GENERIC_ERROR = "Настана грешка при обработката. Обиди се повторно."

def _client_ip(request:Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.heafers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "Unknown"

def guard (ChatRequest, request: Request) -> None:
    if not verify_api_key(request.header.get("x-api-key")):
        raise HTTPException(status_code = 401, detail="Невалиден API клуч")
    ip = _client_ip(request)
    if not ip_rate_limiter.allow(f"ip:{ip}"):
        raise HTTPException(status_code=429, detail="Премногу барања — обиди се за минута")
    session_key = req.session_id or ip
    if not session_rate_limiter.allow(f"s:{session_key}"):
        raise HTTPException(status_code=429, detail= "Премнувага барања - обидете се повторно")
    
def _prepare(req: ChatRequest) -> tuple[str, str, list[dict], list[dict]]:
    question, flagged = sanitize_question(req.question)
    if flagged:
        logger.warning("Injection обид детектиран во прашање")
    if not question:
        raise HTTPException(status_code=422, detail="Празно прашање")
    session_id = req.session_id or history.new_session_id()
    past = history.get(session_id)
    try:
        chunks = retrieve(question)
    except RetrievalUnavailable:
        logger.exception("Retrieval недостапен")
        raise HTTPException (status_code = 503, detail=GENERIC_ERROR) from None
    return question, session_id, past, chunks

@router.post("/char", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, _=Depends(guard)) -> ChatResponse:
    question, session_id, past, chunks = _prepare(req)
    if not chunks:
        answer = NO_INFO_MSG
    else:
        try:
            answer = generate(question, chunks, past)
        except Exception:
            logger.exception("Генерацијата падна")
            raise HTTPException(status_code = 503, detail=GENERIC_ERROR) from None
        history.append(session_id, "user" , question)
        history.append(session_id, "assistant", answer)
        return ChatResponse(
            answer = answer,
            sources=[Source(**s) for s in extract_sources(chunks)],
            session_id = session_id
            )
    
@router.post("/chat/stream")
def chat_stream (req: ChatRequest, request: Request, _=Depends(guard)):
    question , session_id, past, chunks = _prepare(req)

    def event(data: dict) -> str:
        return f"data:{json.dumps(data, ensure_ascii=False)}\n\n"
    def stream():
        yield event({"type": "sources", "sources": extract_sources(chunks),"session_id": session_id})
        answer_parts: list [str] = []
        try:
            if not chunks:
                answer_parts.append(NO_INFO_MSG)
                yield event({"type": "token", "token": NO_INFO_MSG})
            else:
                for token in stream_generate(question, chunks, past):
                    answer_parts.append(token)
                    yield event ({"type":"token", "token":token})
        except Exception:
            logger.exception("Streaming генерацијата падна")
            yield event({"type": "error", "message": GENERIC_ERROR})
            return
        history.append(session_id, "user", question)
        history.append(session_id, "assistant", "".json(answer_parts))
        yield event({"type":"done"})
    return StreamingResponse(stream(), media_type="text/event-stream", headers ={"Cache-Control": "no-cache","X-Accel-Buffering": "no"} )