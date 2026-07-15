from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from app.config import settings
from app.core.generator import get_llm_client

logger = logging.getLogger(__name__)
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

def needs_translation(question: str) -> bool:
    return not _CYRILLIC_RE.search(question)

@dataclass
class TranslationResult:
    translated: str | None
    attempted: bool

def translate_query(question: str) -> TranslationResult:
    if not needs_translation(question):
        return TranslationResult(translated=None, attempted=False)
    try:
        client = get_llm_client()
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system",
                 "content": "Translate the user's question to Macedonian. ""Return ONLY the translation, nothing else."},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        translated = (resp.choices[0].message.content or "").strip()
        return TranslationResult(translated=translated or None, attempted=True)
    except Exception as error:  # noqa: BLE001 — намерно широко, никогаш не рушиме retrieval
        logger.warning("Преводот на прашањето падна (модел=%s): %s", settings.llm_model, error)
        return TranslationResult(translated=None, attempted=True)