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
from app.security import (ip_rate_limiter, sanitize_question, session_rate_limiter, verify_api_key)

logger = logging.getLogger(__name__)  #kreiranje na logger, za da moze da vidam vo log od kade doaga odgovorort
router = APIRouter()
# Poraka koja se prikazuva koga LLM ne moze da najde soodveten odgovor
NO_INFO_MSG = ("Немам информација за тоа во достапната документација. " 
               "Обрати се до Студентска служба на УГД за помош.")
# greska kon klientot, ne sodrze nikakvo izvestuvanje za toa od koj tip na gresja e
GENERIC_ERROR = "Настана грешка при обработката. Обиди се повторно."

# funkcija koja ja vraka ip adresata na klientot od koe ide baranjeto
def _client_ip(request: Request) -> str:
    # x-forwarded-for se pocituva samo ako sme zad reverse proxy inaku klineto moze da go lazira i da go zaobikoli ip limitot
    if settings.trust_proxy_headers:
        prosleden = request.headers.get("x-forwarded-for")  # go cita headerot sto proxy to go postavuva so realnata ip adresa na klientoto
        if prosleden: # dokolku postoi se zima prvata ip adresa, split(",")[0] ja zema prvata adresa, a .strip() brise prazni mesta
            return prosleden.split(",")[0].strip()
    return request.client.host if request.client else "unknown" # inaku se zema ip direktno od konekcijata, ako ja nema se dava unknown

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
    prashanje, session_id, prethodni_poraki, parchinja = _prepare(req)  # se zemaat site 4 paketi sto prethodno se vrateni
    if not parchinja:   # dokolku retrieval ne pronajde nesto relevantno
        odgovor = NO_INFO_MSG   # se vraka porakata
    else: # inaku dokolku ima kontekst, se generira odgovor
        try:
            odgovor = generate(prashanje, parchinja, prethodni_poraki)  # se povikuva LLM na pronajdentot prasanje
        except Exception:  # se vraka bilo koja greska 
            logger.exception("Генерацијата падна")
            raise HTTPException(status_code=503, detail=GENERIC_ERROR) from None    # se dava 503 error na klientska strana, bez da imame tehnicki objasnuvanje 
    history.append(session_id, "user", prashanje)   #se zapisuva vo istorijata so uloga user, za da se zacuva dokolku llm padne pred da vrate odgovor
    history.append(session_id, "assistant", odgovor) # se zapisuva odgovorot so uloga assistant
    return ChatResponse( # se sostavuva finalniot odgovor spored modelot
        answer=odgovor, # tekstot na odgovorot
        sources=[Source(**izvor) for izvor in extract_sources(parchinja)],  # extract_sources vraka recenica, source sekoja recenija ja pretvara vo source objekt 
        session_id=session_id,  # go dava session_id za klientoto da go prati vo slednoto baranje za da moze da imam vrzano baranje
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request, _=Depends(guard)):
    prashanje, session_id, prethodni_poraki, parchinja = _prepare(req)
    def event(podatoci: dict) -> str:   # se foramtira recenicata vo sse format
        return f"data: {json.dumps(podatoci, ensure_ascii=False)}\n\n"  # sse bara tocno data <tekst>\n\n. ensure_ascii ja pravi kirilicata citliva 
    def stream():   # generator funkcija sekoj `yield` praka edno parce kon klientot bez da ceka da se dobie se
        yield event({"type": "sources", "sources": extract_sources(parchinja), "session_id": session_id}) #widgetot moze da gi prikaze referencite dodeka odgovoror uste se pisuva
        delovi_odgovor: list[str] = []  # se sobira listata na site tokeni za na kraj da go zacuvame celiot odgovor vo istorijata
        try:
            if not parchinja:   # dokolku nema konktest
                delovi_odgovor.append(NO_INFO_MSG)  # se dava porakata
                yield event({"type": "token", "token": NO_INFO_MSG})  # prati ja kako eden token
            else:
                for token in stream_generate(prashanje, parchinja, prethodni_poraki): #stream_generate e generatot sto dava del po del od odgovorot kako sto pristignuva od LLM 
                    delovi_odgovor.append(token) # se cuva tokento za istorijata
                    yield event({"type": "token", "token": token})# se ispraka tokentot vo momentot koga pristignuva
        except Exception:  # dokolku nesto padne dodeka se generira 
            logger.exception("Streaming генерацијата падна")
            yield event({"type": "error", "message": GENERIC_ERROR})# se dava GENERIC_ERROR prikazana pogore
            return  # se prekinuva generatorot
        history.append(session_id, "user", prashanje)
        history.append(session_id, "assistant", "".join(delovi_odgovor))
        yield event({"type": "done"}) # se dava signal deka odgovorot e zavrasen 
# se dava generatorot kako strema
    return StreamingResponse(stream(), media_type="text/event-stream",headers={"Cache-Control": "no-cache","X-Accel-Buffering": "no"})
