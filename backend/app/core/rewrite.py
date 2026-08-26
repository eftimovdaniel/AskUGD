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

_FOLLOWUP = re.compile(
    r"(?i)"
    r"^(а|па|и)\s+"
    r"|^(and|what about|how much is (that|it)|the same|same for)\b"
    r"|\b(тоа|ова|она|истиот|истата|истото|that|those)\b"
)
_NAVODNICI = str.maketrans("", "", "\"'“”«»")


def treba_rewrite(prashanje: str, istorija: list[dict]) -> bool:
    if not settings.use_query_rewrite or not istorija:
        return False
    return bool(_FOLLOWUP.search((prashanje or "").strip()))


def rewrite_query(prashanje: str, istorija: list[dict]) -> str:
    if not treba_rewrite(prashanje, istorija):
        return prashanje
    posledni = []
    for poraka in istorija:
        role = "Студент" if poraka.get("role") == "user" else "Асистент"
        posledni.append(f"{role}: {(poraka.get('content') or '')[:400]}")
    try:
        consume_llm()
        resp = get_llm_client().chat.completions.create(
            model=settings.llm_model,
            temperature=0.0,
            max_tokens=80,
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
            rewritten = rewritten.split(":", 1)[-1].strip()
        if not (3 <= len(rewritten) <= 300):
            return prashanje
        logger.info("Query rewrite: %r → %r", prashanje, rewritten)
        return rewritten
    except LlmBudgetExceeded:
        logger.warning("Query rewrite прескокнат — LLM буџет")
        return prashanje
    except Exception as greshka:
        logger.warning("Query rewrite падна: %s", greshka)
        return prashanje
