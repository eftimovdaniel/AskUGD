# HTTP sloj: guard, JSON i SSE. Delovniot tek e vo app.core.pipeline.
from __future__ import annotations
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.config import settings
from app.core.budget import BUDGET_MSG, LlmBudgetExceeded
from app.core.generator import generate, stream_generate
from app.core.pipeline import EmptyQuestion, Ready, commit, plan, start_turn
from app.core.retriever import RetrievalUnavailable
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.security import chat_allowed, ip_rate_limiter, session_rate_limiter

ACCESS_DENIED = "Пристапот не е дозволен."

logger = logging.getLogger(__name__)
router = APIRouter()
GENERIC_ERROR = "Настана грешка при обработката. Обиди се повторно."


def _client_ip(request: Request) -> str:
    direkten = request.client.host if request.client else "unknown"
    if not settings.trust_proxy_headers:
        return direkten
    prosleden = request.headers.get("x-forwarded-for")
    if not prosleden:
        return direkten
    lanec = [ip.strip() for ip in prosleden.split(",") if ip.strip()]
    if not lanec:
        return direkten
    indeks = settings.trusted_proxy_hops
    if len(lanec) >= indeks + 1:
        return lanec[-(indeks + 1)]
    return lanec[0]


def guard(req: ChatRequest, request: Request) -> None:
    if not chat_allowed(request.headers.get("origin"), request.headers.get("x-api-key")):
        raise HTTPException(status_code=403, detail=ACCESS_DENIED)
    ip_adresa = _client_ip(request)
    if not ip_rate_limiter.allow(f"ip:{ip_adresa}"):
        raise HTTPException(status_code=429, detail="Премногу барања — обиди се за минута")
    kluc_sesija = req.session_id or ip_adresa
    if not session_rate_limiter.allow(f"s:{kluc_sesija}"):
        raise HTTPException(status_code=429, detail="Премногу барања — обиди се за минута")


def _sse(podatoci: dict) -> str:
    return f"data: {json.dumps(podatoci, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, _=Depends(guard)) -> ChatResponse:
    try:
        turn = start_turn(req.question, req.session_id)
        planiran = plan(turn)
    except EmptyQuestion as greshka:
        raise HTTPException(status_code=422, detail=str(greshka)) from None
    except LlmBudgetExceeded:
        raise HTTPException(status_code=503, detail=BUDGET_MSG) from None
    except RetrievalUnavailable:
        logger.exception("Retrieval недостапен")
        raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None

    if isinstance(planiran, Ready):
        gotov = commit(turn, planiran.answer, planiran.sources, cacheable=planiran.cacheable)
        return ChatResponse(
            answer=gotov.answer,
            sources=[Source(**izvor) for izvor in gotov.sources],
            session_id=turn.session_id,
        )

    try:
        odgovor = generate(turn.prashanje, planiran.parchinja, turn.istorija)
    except LlmBudgetExceeded:
        raise HTTPException(status_code=503, detail=BUDGET_MSG) from None
    except Exception:
        logger.exception("Генерацијата падна")
        raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None

    gotov = commit(turn, odgovor, planiran.sources, cacheable=True)
    return ChatResponse(
        answer=gotov.answer,
        sources=[Source(**izvor) for izvor in gotov.sources],
        session_id=turn.session_id,
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request, _=Depends(guard)):
    try:
        turn = start_turn(req.question, req.session_id)
    except EmptyQuestion as greshka:
        raise HTTPException(status_code=422, detail=str(greshka)) from None

    def stream():
        try:
            planiran = plan(turn)
        except RetrievalUnavailable:
            logger.exception("Retrieval недостапен")
            yield _sse({"type": "error", "message": GENERIC_ERROR})
            return
        except LlmBudgetExceeded:
            yield _sse({"type": "error", "message": BUDGET_MSG})
            return

        if isinstance(planiran, Ready):
            gotov = commit(turn, planiran.answer, planiran.sources, cacheable=planiran.cacheable)
            yield _sse({
                "type": "sources",
                "sources": gotov.sources,
                "session_id": turn.session_id,
            })
            yield _sse({"type": "token", "token": gotov.answer})
            yield _sse({"type": "done"})
            return

        yield _sse({"type": "sources", "sources": planiran.sources, "session_id": turn.session_id})
        delovi: list[str] = []
        try:
            for token in stream_generate(turn.prashanje, planiran.parchinja, turn.istorija):
                delovi.append(token)
                yield _sse({"type": "token", "token": token})
        except LlmBudgetExceeded:
            yield _sse({"type": "error", "message": BUDGET_MSG})
            return
        except Exception:
            logger.exception("Streaming генерацијата падна")
            yield _sse({"type": "error", "message": GENERIC_ERROR})
            return
        gotov = commit(turn, "".join(delovi), planiran.sources, cacheable=True)
        if gotov.scrubbed:
            # tokenite vekje zaminale — zameni go prikazot; istorijata e cista
            yield _sse({"type": "redact", "message": gotov.answer})
        yield _sse({"type": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
