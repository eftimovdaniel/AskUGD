#preveduvanje na prasanjeot na makedonski za da moze da se pobrzo i polesno prebaruvanje
#Dokumentacijata e na makedonski. Anglisko prasanje → LLM prevod. Mk-латиница („kolku cini upis“)
#se pretvora vo кирилица bez LLM. Kirilica se ostava kako sto e
from __future__ import annotations
import logging
from dataclasses import dataclass
from app.config import settings
from app.core.budget import LlmBudgetExceeded, consume_llm
from app.core.generator import get_llm_client
from app.core.language import ima_kirilica, is_mk_latin, transliterate_mk

logger = logging.getLogger(__name__)

def needs_translation(question: str) -> bool:
    """True ako dokumentacijata e na MK, a prasanjeto e na drug jazik (ne mk-latinica)."""
    return not ima_kirilica(question) and not is_mk_latin(question)

@dataclass
class TranslationResult:    # rezlutat od obidot za prevod
    translated: str | None #prevod ili none
    # attempted gi razlikuva „nemase potreba“ od „probav i padna“ — retriever-ot
    # spored toa znae dali da logira problem ili prosto da prodolzi so originalot.
    attempted: bool # dali ima obid za prevod ili ne

def translate_query(question: str) -> TranslationResult:
    """Prevodot se DODAVA kon originalot vo retrieval, ne go zamenuva — los prevod ne steti."""
    if ima_kirilica(question):
        return TranslationResult(translated=None, attempted=False)
    if is_mk_latin(question):
        prevod = transliterate_mk(question)
        # Ako transliteracijata ne smenila nisto, dodavanjeto ista niza samo bi ja
        # udvoila rabotata na prebaruvanjeto bez nov kandidat.
        if prevod and prevod.lower() != question.lower():
            logger.info("Транслитерација: %r → %r", question, prevod)
            return TranslationResult(translated=prevod, attempted=True)
        return TranslationResult(translated=None, attempted=False)
    try:
        # Istiot kap kako generate/rewrite — inaku prevodot bi bil „besplaten“ LLM povik.
        consume_llm()
        client = get_llm_client()
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system",
                 "content": "Translate the user's question to Macedonian. Return ONLY the translation, nothing else."},
                {"role": "user", "content": question},
            ],
            temperature=0.0,     # prevod, ne prepev — sakame ist izlez za ist vlez
            max_tokens=200,
        )
        translated = (resp.choices[0].message.content or "").strip()
        return TranslationResult(translated=translated or None, attempted=True)
    except LlmBudgetExceeded:
        raise
    except Exception as error:
        # Padnat prevod ne go prekinuva prasanjeto: prebaruvanjeto odi so originalot.
        logger.warning("Преводот на прашањето падна (модел=%s): %s", settings.llm_model, error)
        return TranslationResult(translated=None, attempted=True)
