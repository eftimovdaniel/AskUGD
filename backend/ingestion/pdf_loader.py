from __future__ import annotations
import logging
import re
from pathlib import Path
import fitz  # PyMuPDF
logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 50 * 1024 * 1024   # 50 MB
MAX_PAGES = 500

# Линии/шаблони што се повторуваат на секоја страница и не носат значење
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

# Невидливи карактери: zero-width простори, BOM, soft hyphen
_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")

class PdfError(Exception):
    """Грешка при вчитување PDF (безбедна порака, без стек кон корисник)."""

def clean_text(text: str) -> str:
    """Отстрани шум, невидливи карактери и вишок празни линии."""
    text = _NOISE_RE.sub(" ", text)
    text = _INVISIBLE_RE.sub("", text)
    text = text.replace("\xa0", " ")
    # контролни карактери освен \n и \t
    text = "".join(znak for znak in text
                   if znak == "\n" or znak == "\t" or ord(znak) >= 32)
    text = re.sub(r"\n\s*\n+", "\n\n", text)   # повеќекратни празни линии -> една
    text = re.sub(r"[ \t]+", " ", text)        # вишок празни места
    return text.strip()

def _extract(dokument: fitz.Document, name: str) -> str:
    """Заеднички дел: провери документ и извади чист текст од сите страници."""
    if dokument.needs_pass:
        raise PdfError(f"'{name}' е заштитен со лозинка — прескокнат")
    if dokument.page_count > MAX_PAGES:
        raise PdfError(f"'{name}' има {dokument.page_count} страници (лимит {MAX_PAGES})")
    stranici: list[str] = []
    for page_no in range(dokument.page_count):
        try:
            surov = dokument.load_page(page_no).get_text("text")
        except Exception as greshka:  # оштетена страница — логирај и продолжи
            logger.warning("Прескокната страница %d во '%s': %s",
                           page_no + 1, name, greshka)
            continue
        iscisten = clean_text(surov)
        if iscisten:
            stranici.append(iscisten)
    if not stranici:
        raise PdfError(f"'{name}' не содржи извлечлив текст")
    return "\n\n".join(stranici)

def load_pdf(path: str | Path) -> str:
    pateka = Path(path)
    if not pateka.is_file():
        raise PdfError(f"Фајлот не постои: {pateka.name}")
    if pateka.stat().st_size > MAX_FILE_BYTES:
        raise PdfError(f"'{pateka.name}' е поголем од {MAX_FILE_BYTES // (1024*1024)} MB")
    try:
        with fitz.open(pateka) as dokument:
            return _extract(dokument, pateka.name)
    except PdfError:
        raise
    except Exception as greshka:
        raise PdfError(f"Не може да се отвори '{pateka.name}': {greshka}") from greshka

def load_pdf_bytes(podatoci: bytes, name: str = "<web-pdf>") -> str:
    if len(podatoci) > MAX_FILE_BYTES:
        raise PdfError(f"'{name}' е поголем од {MAX_FILE_BYTES // (1024*1024)} MB")
    try:
        with fitz.open(stream=podatoci, filetype="pdf") as dokument:
            return _extract(dokument, name)
    except PdfError:
        raise
    except Exception as greshka:
        raise PdfError(f"Не може да се парсира '{name}': {greshka}") from greshka

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(load_pdf(sys.argv[1])[:2000])
