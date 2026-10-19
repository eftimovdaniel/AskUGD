# Follow-up („а тоа?“, „а за втор циклус?“) → edna samostojna rečenica za prebaruvanje.
# Ne se aktivira za obični kratki prasanja posle pozdrav — inaku sekoj „колку чини упис?“
# bi platil extra LLM povik i bi rizikuvnal los rewrite.
from __future__ import annotations
import logging
import re
from app.config import settings
from app.core.budget import LlmBudgetExceeded, consume_llm
from app.core.generator import get_llm_client, llm_extra

logger = logging.getLogger(__name__)

# „^“ kaj vrskite e zadolzitelno: „а“, „па“, „и“ nadovrzuvaat samo na pocetok na
# recenica — vo sredina se obicni vrski („упис и заверка“) i ne znacat nadovrzuvanje.
_FOLLOWUP = re.compile(
    r"(?i)"
    r"^(а|па|и)\s+"
    r"|^(and|what about|how much is (that|it)|the same|same for)\b"
    r"|\b(тоа|ова|она|истиот|истата|истото|that|those)\b"
)
# Modelot ponekogas go vrakja prevodot vo navodnici; tie bi zaminale vo vektorot.
_NAVODNICI = str.maketrans("", "", "\"'“”«»")


def treba_rewrite(prashanje: str, istorija: list[dict]) -> bool:
    """Bez istorija nema na sto da se nadovrze, pa prvoto prasanje nikogas ne se prerabotuva."""
    if not settings.use_query_rewrite or not istorija:
        return False
    return bool(_FOLLOWUP.search((prashanje or "").strip()))


def rewrite_query(prashanje: str, istorija: list[dict]) -> str:
    """Vrakja samostojno prasanje za prebaruvanje; pri sekoj neuspeh — originalot."""
    if not treba_rewrite(prashanje, istorija):
        return prashanje
    posledni = []
    for poraka in istorija:
        role = "Студент" if poraka.get("role") == "user" else "Асистент"
        # Kratenje na 400 znaci: za kontekst e dovolno, a spreci eden dolg odgovor
        # od prethodniot potez da go napolni promptot na ovoj pomosen povik.
        posledni.append(f"{role}: {(poraka.get('content') or '')[:400]}")
    try:
        consume_llm()
        resp = get_llm_client().chat.completions.create(
            model=settings.llm_model,
            temperature=0.0,      # prerabotkata treba da e predvidliva, ne kreativna
            max_tokens=80,        # bara se edna recenica; kap protiv „razgovorliv“ model
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Претвори го последното прашање во ЕДНА самостојна "
                        "реченица за пребарување во документација на УГД. "
                        "Без одговор, без наводници, само реченицата."
                    ),
                },
                {
                    "role": "user",
                    "content": "\n".join(posledni) + f"\nСтудент: {prashanje}",
                },
            ],
            **llm_extra(),
        )
        rewritten = (resp.choices[0].message.content or "").strip().translate(_NAVODNICI)
        if rewritten.lower().startswith("прашање"):
            rewritten = rewritten.split(":", 1)[-1].strip()   # modelot ja povtoril etiketata
        # Prekratko znaci prazen odgovor, predolgo znaci deka modelot pocnal da objasnuva
        # namesto da preraboti — i vo dvata slucaja originalot e posiguren.
        if not (3 <= len(rewritten) <= 300):
            return prashanje
        logger.info("Query rewrite: %r → %r", prashanje, rewritten)
        return rewritten
    # Pomosen cekor sto padnal ne smee da go sobori glavniot tek — prebaruvanjeto
    # prodolzuva so originalot, samo so poslab rezultat.
    except LlmBudgetExceeded:
        logger.warning("Query rewrite прескокнат — LLM буџет")
        return prashanje
    except Exception as greshka:
        logger.warning("Query rewrite падна: %s", greshka)
        return prashanje
