#preveduvanje na prasanjeot na makedonski za da moze da se pobrzo i polesno prebaruvanje
#Dokumentacijata e na makedonski. Anglisko prasanje → LLM prevod. Mk-латиница („kolku cini upis“)
#se pretvora vo кирилица bez LLM. Kirilica se ostava kako sto e
from __future__ import annotations
import logging
from dataclasses import dataclass
from app.config import settings
from app.core.generator import get_llm_client
from app.core.language import ima_kirilica, is_mk_latin, transliterate_mk

logger = logging.getLogger(__name__)

def needs_translation(question: str) -> bool:
    return not ima_kirilica(question) and not is_mk_latin(question)

@dataclass
class TranslationResult:    # rezlutat od obidot za prevod
    translated: str | None #prevod ili none
    attempted: bool # dali ima obid za prevod ili ne

def translate_query(question: str) -> TranslationResult:
    if ima_kirilica(question):
        return TranslationResult(translated=None, attempted=False)
    if is_mk_latin(question):
        prevod = transliterate_mk(question)
        if prevod and prevod.lower() != question.lower():
            logger.info("Транслитерација: %r → %r", question, prevod)
            return TranslationResult(translated=prevod, attempted=True)
        return TranslationResult(translated=None, attempted=False)
    try:
        client = get_llm_client()
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system",
                 "content": "Translate the user's question to Macedonian. Return ONLY the translation, nothing else."},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        translated = (resp.choices[0].message.content or "").strip()
        return TranslationResult(translated=translated or None, attempted=True)
    except Exception as error:
        logger.warning("Преводот на прашањето падна (модел=%s): %s", settings.llm_model, error)
        return TranslationResult(translated=None, attempted=True)
