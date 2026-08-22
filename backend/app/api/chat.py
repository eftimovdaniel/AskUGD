#glaven endpoint, go povrazuva celiot rag tek, postavuvanje na prasanje - retrieval - generiranje odgovor

from __future__ import annotations
import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.config import settings
from app.core.cache import answer_cache, normalize_key
from app.core.generator import generate, stream_generate
from app.core.history import history
from app.core.retriever import RetrievalUnavailable, extract_sources, retrieve
from app.models.schemas import ChatRequest, ChatResponse, Source
from app.security import (ip_rate_limiter, sanitize_question, session_rate_limiter, verify_api_key)

logger = logging.getLogger(__name__)  #kreiranje na logger, za da moze da vidam vo log od kade doaga odgovorort
router = APIRouter()
# Poraka koja se prikazuva koga LLM ne moze da najde soodveten odgovor
NO_INFO_MSG = ("Немам информација за тоа во достапната документација. " 
               "Обрати се до Студентска служба на УГД за помош.")
# greska kon klientot, ne sodrze nikakvo izvestuvanje za toa od koj tip na gresja e
GENERIC_ERROR = "Настана грешка при обработката. Обиди се повторно."

# Fiksen pozdrav za razgovorni prasanja (zdravo, koj si ti, fala...) — se vraka BEZ pretrazuvanje
# i BEZ LLM: konzistenten e sekojpat i ne troshi tokeni od dnevnata kvota.
POZDRAV_MSG = "Здраво, како може да ви помогнам?"
_POZDRAV_RE = re.compile(
    r"(здраво|здр|ало|еј|хеј|поздрав|добар\s+ден|добро\s+утро|добра\s+вечер|"
    r"кој\s+си|ко\s+си|што\s+си|што\s+(можеш|правиш|нудиш)|со\s+што\s+(можеш|помагаш)|"
    r"фала|благодар|zdravo|koj\s+si|sto\s+mozes|fala|hi|hello|hey|"
    r"who\s+are\s+you|what\s+can\s+you|thanks|thank\s+you)",
    re.IGNORECASE,
)
def _e_pozdrav(prashanje: str) -> bool:  # kratko razgovorno prasanje -> fiksen pozdrav
    tekst = prashanje.strip().lower()
    if len(tekst.split()) > 5:   # podolgi prasanja odat niz normalniot tek
        return False
    return bool(_POZDRAV_RE.search(tekst))
# Detekcija na obid da se izvlece sistemskiot prompt / instrukcii -> tvrdo odbivanje (bez LLM).
ODBIENO_MSG = ("Не можам да ги споделам внатрешните инструкции или начинот на работа на системот. "
               "Со задоволство ќе ти помогнам со прашање за студирањето на УГД.")
_IZVLEK_RE = re.compile(
    r"(?i)("
    r"system\s*prompt|developer\s+(message|prompt)|initial\s+(instructions?|prompt)|"
    r"(reveal|show|print|repeat|give|display|output|share|tell)\s+(me\s+)?(your|the)?\s*(system\s*)?(prompt|instructions?|rules?|guidelines?|configuration)|"
    r"(repeat|print|output|say)\s+(the\s+)?(text|words|everything)\s+above|"
    r"what\s+(are|were)\s+your\s+(instructions?|rules?|system\s*prompt)|verbatim|"
    r"системск\w*\s+промпт|"
    r"(покажи|кажи|издиктирај|повтори|испечати|откриј|сподели|дај)\s+(ми\s+)?(ги\s+)?(твоите|своите)?\s*(инструкции|правила|промпт|упатства|насоки)|"
    r"(повтори|испечати|кажи)\s+(го\s+)?(текстот|зборовите|сето)\s+(погоре|над)|"
    r"кои\s+се\s+(твоите|вашите)\s+(инструкции|правила)"
    r")"
)
def _e_obid_izvlekuvanje(prashanje: str) -> bool:
    return bool(_IZVLEK_RE.search(prashanje or ""))

# funkcija koja ja vraka ip adresata na klientot od koe ide baranjeto
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

#bezbednosna porata se izvrasuva pred sekoj povik
def guard(req: ChatRequest, request: Request) -> None:
    if not verify_api_key(request.headers.get("x-api-key")): # proverka na API key od headerot, verify_api_key vraka True i ako klicot voopsto ne e konfiguriran 
        raise HTTPException(status_code=401, detail="Невалиден API клуч")
    ip_adresa = _client_ip(request) #se zima ip adresata za ip limitot
    if not ip_rate_limiter.allow(f"ip:{ip_adresa}"): #se proveruva ip limitot, so ip: {ip_adresa} se odvojuva klucit id sesiskite vo istiot sklad
        raise HTTPException(status_code=429, detail="Премногу барања — обиди се за минута")
    kluc_sesija = req.session_id or ip_adresa   # kluc za sesiskiot limit: session_id ako postoi inaku paga nazad na ip
    if not session_rate_limiter.allow(f"s:{kluc_sesija}"):
        raise HTTPException(status_code=429, detail="Премногу барања — обиди се за минута")

# zadnicki dva endpoints, za da ne se povtoruva istiot kod dvapati
def _prepare(req: ChatRequest) -> tuple[str, str, list[dict], list[dict]]:
    prashanje, oznaceno = sanitize_question(req.question) #se ciste prasanjeto od nepotrebni znaci i simboli za da se dobie cisto prasanje za obrabotka
    if oznaceno: # dokolku se detektira obid za Injection, ne dava nisto, samo vo logovite se pecate deka ima obid
        logger.warning("Injection обид детектиран во прашање")
    if not prashanje:  # dokolku po cistenje na prasanjeto ostane prazno, samo na primer nekoj znak
        raise HTTPException(status_code=422, detail="Празно прашање") #se pecate error greska

    session_id = req.session_id or history.new_session_id() # se zema session_id od razgovorot, dokolku nema se kreira nov, se koriste za da moze da se koriste follow up na prasanjeto
    prethodni_poraki = history.get(session_id)  # se zema poslednata poraka za taa sesija
    try:    # se pravi obid da se najde relevanto parce 
        parchinja = retrieve(prashanje) # tekot na podatoci: prevod = hybrid search = rerank = najrelevantno parce
    except RetrievalUnavailable:    # dokolku bazata e down 
        logger.exception("Retrieval недостапен")    # se pecati porakata vo terminal, logovite
        raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None # na korisnikot mu se dava 503 = servisot e primremeno nedostapen,
    return prashanje, session_id, prethodni_poraki, parchinja # se vrakaat site vrednosti

# 
@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, _=Depends(guard)) -> ChatResponse:
    prashanje, oznaceno = sanitize_question(req.question)
    if oznaceno:
        logger.warning("Injection обид детектиран во прашање")
    if not prashanje:
        raise HTTPException(status_code=422, detail="Празно прашање")

    session_id = req.session_id or history.new_session_id()
    prethodni_poraki = history.get(session_id)

    if _e_pozdrav(prashanje):   # razgovorno prasanje -> fiksen pozdrav (bez LLM)
        return ChatResponse(answer=ODBIENO_MSG, sources=[], session_id=session_id)
    kluc_kes = normalize_key(prashanje) if not prethodni_poraki else None
    if kluc_kes is not None:
        kesirano = answer_cache.get(kluc_kes)
        if kesirano is not None:
            odgovor, izvori = kesirano
            history.append(session_id, "user", prashanje)
            history.append(session_id, "assistant", odgovor)
            return ChatResponse(
                answer=odgovor,
                sources=[Source(**izvor) for izvor in izvori],
                session_id=session_id,
            )

    try:
        parchinja = retrieve(prashanje)
    except RetrievalUnavailable:
        logger.exception("Retrieval недостапен")
        raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None

    if not parchinja:
        odgovor = NO_INFO_MSG
    else:
        try:
            odgovor = generate(prashanje, parchinja, prethodni_poraki)
        except Exception:
            logger.exception("Генерацијата падна")
            raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None

    izvori = extract_sources(parchinja)
    if kluc_kes is not None and parchinja:
        answer_cache.set(kluc_kes, (odgovor, izvori))

    history.append(session_id, "user", prashanje)
    history.append(session_id, "assistant", odgovor)
    return ChatResponse(
        answer=odgovor,
        sources=[Source(**izvor) for izvor in izvori],
        session_id=session_id,
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request, _=Depends(guard)):
    prashanje, oznaceno = sanitize_question(req.question)
    if oznaceno:
        logger.warning("Injection обид детектиран во прашање")
    if not prashanje:
        raise HTTPException(status_code=422, detail="Празно прашање")

    session_id = req.session_id or history.new_session_id()
    prethodni_poraki = history.get(session_id)
    kluc_kes = normalize_key(prashanje) if not prethodni_poraki else None

    def event(podatoci: dict) -> str:
        return f"data: {json.dumps(podatoci, ensure_ascii=False)}\n\n"

    def stream():
        if _e_obid_izvlekuvanje(prashanje):
            yield event({"type": "sources", "sources": [], "session_id": session_id})
            yield event({"type:": "token", "token":ODBIENO_MSG})
            history.append(session_id, "user", prashanje)
            history.append(session_id, "assistant", ODBIENO_MSG)
            yield event ({"type": "done"})
            return
        
        if _e_pozdrav(prashanje):   # razgovorno prasanje -> fiksen pozdrav (bez pretrazuvanje/LLM)
            yield event({"type": "sources", "sources": [], "session_id": session_id})
            yield event({"type": "token", "token": POZDRAV_MSG})
            history.append(session_id, "user", prashanje)
            history.append(session_id, "assistant", POZDRAV_MSG)
            yield event({"type": "done"})
            return
        if kluc_kes is not None:
            kesirano = answer_cache.get(kluc_kes)
            if kesirano is not None:
                odgovor, izvori = kesirano
                yield event({"type": "sources", "sources": izvori, "session_id": session_id})
                yield event({"type": "token", "token": odgovor})
                history.append(session_id, "user", prashanje)
                history.append(session_id, "assistant", odgovor)
                yield event({"type": "done"})
                return

        try:
            parchinja = retrieve(prashanje)
        except RetrievalUnavailable:
            logger.exception("Retrieval недостапен")
            yield event({"type": "error", "message": GENERIC_ERROR})
            return
        izvori = extract_sources(parchinja)
        yield event({"type": "sources", "sources": izvori, "session_id": session_id})
        delovi_odgovor: list[str] = []
        try:
            if not parchinja:
                delovi_odgovor.append(NO_INFO_MSG)
                yield event({"type": "token", "token": NO_INFO_MSG})
            else:
                for token in stream_generate(prashanje, parchinja, prethodni_poraki):
                    delovi_odgovor.append(token)
                    yield event({"type": "token", "token": token})
        except Exception:
            logger.exception("Streaming генерацијата падна")
            yield event({"type": "error", "message": GENERIC_ERROR})
            return
        odgovor = "".join(delovi_odgovor)
        if kluc_kes is not None and parchinja:
            answer_cache.set(kluc_kes, (odgovor, izvori))
        history.append(session_id, "user", prashanje)
        history.append(session_id, "assistant", odgovor)
        yield event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
