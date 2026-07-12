from __future__ import annotations
import logging
from pathlib import Path
import re
import fitz

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PAGES = 500

NOISE_PATTERNS = [
    r"УНИВЕРЗИТЕТСКИ\s+ГЛАСНИК",
    r"Број\s+\d+,\s*\w+\s+\d{4}",
    r"Ознака:\s*\S+",
    r"Верзија:\s*\S+",
    r"Страница\s*\d+\s*/\s*\d+",
    r"Овој документ е сопственост.*?авторски права\.",  # disclaimer
    r"Забрането е\s+фотографирање.*?запис\.",
]
_NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE | re.DOTALL)

_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")

class PdfError(Exception):
    """Грешка при вчитување PDF (безбедна порака, без стек кон корисник)."""

def clean_text(text: str)-> str:
    text = _NOISE_RE.sub(" ", text)
    text = _INVISIBLE_RE.sub("", text)
    text = text.replace("\xa0", " ")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()

def _extract(doc: fitz.Document, name: str) -> str:
    if doc.needs_pass:
        raise PdfError(f"'{name}' е заштитен со лозинка — прескокнат") 
    if doc.page_count > MAX_PAGES:
        raise PdfError(f"'{name}' има {doc.page_count} страници, но лимит {MAX_PAGES})")
    
    pages: list[str] = []
    for page_no in range(doc.page_count):
        try:
            raw = doc.load_page(page_no).get_text("text")
        except Exception as e:
            logger.warning("Прескокната страница %d во '%s': %s", page_no + 1, name, e)
            continue
        cleaned = clean_text(raw)
        if cleaned:
            pages.append(cleaned)
        if not pages:
            raise PdfError(f"'{name}' нема текст за извлекување")
        return "\n\n".join(pages)
    
def load_pdf(path: Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise PdfError(f"Фајлот не е пронајден: '{path}'")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise PdfError(f"'{p.name}' е поголем од {MAX_FILE_BYTES // (1024*1024)} MB")
    try:
        with fitz.open(p) as doc:
            return _extract(doc, p.name)
    except Exception as e:
        raise PdfError(f"Грешка при отворање на '{p.name}': {e}") from e

def loaf_pdf_bytes (data: bytes, name: str = "<web_pdf>") -> str:
    if len (data) > MAX_FILE_BYTES:
        raise PdfError(f"'{name}' е поголем од {MAX_FILE_BYTES // (1024*1024)} MB")
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return _extract(doc, name)
    except Exception as e:
        raise PdfError(f"Грешка при отворање на '{name}': {e}") from e
    
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(load_pdf(sys.argv[1])[:2000])