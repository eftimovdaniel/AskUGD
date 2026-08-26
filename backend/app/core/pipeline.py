# Eden tek za /chat i /chat/stream: namera → kes → retrieval → generate.
from __future__ import annotations
import logging
from dataclasses import dataclass
from app.core.cache import answer_cache, normalize_key
from app.core.history import history
from app.core.intents import fiksna_namera, scrub_leaked_answer
from app.core.language import pick_lang
from app.core.retriever import extract_sources, retrieve
from app.core.sessions import resolve_session_id
from app.security import sanitize_question

logger = logging.getLogger(__name__)

_NO_INFO = {
    "mk": (
        "Немам информација за тоа во достапната документација. "
        "Обрати се до Студентска служба на УГД за помош."
    ),
    "en": (
        "I don't have that information in the available documentation. "
        "Please contact the Student Affairs office at UGD for help."
    ),
    "tr": (
        "Mevcut belgelerde bu bilgi yok. "
        "Yardım için UGD Öğrenci İşleri'ne başvurun."
    ),
    "de": (
        "Dazu habe ich in der verfügbaren Dokumentation keine Information. "
        "Wende dich bitte an die Studentenverwaltung der UGD."
    ),
    "sq": (
        "Nuk kam atë informacion në dokumentacionin e disponueshëm. "
        "Drejtohuni te Shërbimi Studentor i UGD-së për ndihmë."
    ),
}

def no_info_msg(prashanje: str) -> str:
    return _NO_INFO[pick_lang(prashanje, _NO_INFO)]

class EmptyQuestion(ValueError):
    pass

@dataclass
class Turn:
    prashanje: str
    surovo: str
    session_id: str
    istorija: list[dict]
    kluc_kes: str | None


@dataclass
class Ready:
    """Gotov odgovor (namera, kes ili nema dokumentacija)."""
    answer: str
    sources: list[dict]
    cacheable: bool = False

@dataclass
class NeedGenerate:
    parchinja: list[dict]
    sources: list[dict]

@dataclass
class Committed:
    """Ona sto smee da izleze kon klientot, po scrub."""
    answer: str
    sources: list[dict]
    scrubbed: bool = False

def start_turn(surovo: str, session_id: str | None) -> Turn:
    prashanje, oznaceno = sanitize_question(surovo)
    if oznaceno:
        logger.warning("Injection обид детектиран во прашање")
    if not prashanje:
        raise EmptyQuestion("Празно прашање")
    sid = resolve_session_id(session_id)
    istorija = history.get(sid)
    kluc = normalize_key(prashanje) if not istorija else None
    return Turn(
        prashanje=prashanje,
        surovo=surovo,
        session_id=sid,
        istorija=istorija,
        kluc_kes=kluc,
    )

def plan(turn: Turn) -> Ready | NeedGenerate:
    fiksen = fiksna_namera(turn.surovo, turn.prashanje)
    if fiksen is not None:
        return Ready(answer=fiksen, sources=[])
    if turn.kluc_kes is not None:
        kesirano = answer_cache.get(turn.kluc_kes)
        if kesirano is not None:
            odgovor, izvori = kesirano
            return Ready(answer=odgovor, sources=izvori)
    parchinja = retrieve(turn.prashanje, turn.istorija)
    if not parchinja:
        return Ready(answer=no_info_msg(turn.prashanje), sources=[])
    return NeedGenerate(parchinja=parchinja, sources=extract_sources(parchinja))

def commit(turn: Turn, odgovor: str, izvori: list[dict], *, cacheable: bool = False) -> Committed:
    """Zapisi istorija/kes i vrati ona sto smee da izleze kon klientot."""
    # Jazik od SUROVO: ocisteniot tekst nosi „[отстрането]“ (kirilica) i go meša detect.
    clean = scrub_leaked_answer(odgovor, turn.surovo)
    scrubbed = clean != odgovor
    if scrubbed:
        logger.warning("Одговорот е заменет — детектиран истечен системски текст")
        izvori = []
        # NE kesiraj odbivanje pod kluc na normalno prasanje — inaku edno protekuvanje
        # gi truje site sledni istovetni prasanja do istek na TTL.
        if turn.kluc_kes is not None:
            answer_cache.delete(turn.kluc_kes)
    elif cacheable and turn.kluc_kes is not None:
        answer_cache.set(turn.kluc_kes, (clean, izvori))
    history.append(turn.session_id, "user", turn.prashanje)
    history.append(turn.session_id, "assistant", clean)
    return Committed(answer=clean, sources=izvori, scrubbed=scrubbed)
