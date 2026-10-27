# Produkcijski pomošen sloj za OCR: keš, čištenje šum, karantin za lični podatoci.
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent

# šum od pečat / logo što Tesseract često go meša na zaglavieto
_OCR_NOISE_LINE = re.compile(
    r"^("
    r".{0,6}ој\s*of.{0,12}|"
    r".{0,6}oj\s*of.{0,12}|"
    r"of\s*[„\"«]?хи.?|"
    r"универзитет.{0,20}грб|"
    r"republic\s+of\s+macedonia|"
    r"гоце\s+делчев.{0,20}лого"
    r")$",
    re.IGNORECASE,
)
_GARBAGE_LINE = re.compile(r"^[\W\d_|]{0,4}.{0,3}[\W\d_|]{0,6}$")
_PII_NAME_LINE = re.compile(
    r"(?m)^\s*\d+[.)]?\s*[А-ЯA-ZЀ-Џ][а-яa-zѐ-џ]+\s+[А-ЯA-ZЀ-Џ][а-яa-zѐ-џ]+"
)
_QUARANTINE_NAME = re.compile(
    r"(odluka|одлука).{0,40}(particip|партицип)|"
    r"(список|списокот).{0,30}(студент|студенти)|"
    r"rang.?lista|ранг.?лист",
    re.IGNORECASE,
)


def _pateka(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (_BACKEND_ROOT / p)


def cache_dir() -> Path:
    d = _pateka(settings.ocr_cache_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def review_dir() -> Path:
    d = _pateka(settings.ocr_review_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def failed_log_path() -> Path:
    p = _pateka(settings.ocr_failed_log)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def page_fingerprint(pixmap_bytes: bytes, dpi: int, lang: str) -> str:
    h = hashlib.sha256()
    h.update(str(dpi).encode())
    h.update(lang.encode())
    h.update(pixmap_bytes)
    return h.hexdigest()


def citaj_kes(otpecatok: str) -> tuple[str, float] | None:
    f = cache_dir() / f"{otpecatok}.json"
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        tekst = str(data.get("text") or "")
        doverba = float(data.get("confidence") or 0.0)
        return tekst, doverba
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as greska:
        logger.debug("OCR кеш нечитлив %s: %s", f.name, greska)
        return None


def zapisi_kes(otpecatok: str, tekst: str, doverba: float, meta: dict | None = None) -> None:
    zapis = {
        "text": tekst,
        "confidence": doverba,
        "meta": meta or {},
    }
    f = cache_dir() / f"{otpecatok}.json"
    try:
        f.write_text(json.dumps(zapis, ensure_ascii=False, indent=2), encoding="utf-8")
        (cache_dir() / f"{otpecatok}.txt").write_text(tekst, encoding="utf-8")
    except OSError as greska:
        logger.warning("OCR кеш не се запиша %s: %s", f.name, greska)


def clean_ocr_text(text: str) -> str:
    if not text or not text.strip():
        return ""
    redovi = []
    for red in text.splitlines():
        t = red.strip()
        if not t:
            continue
        if _OCR_NOISE_LINE.match(t):
            continue
        if len(t) <= 6 and _GARBAGE_LINE.match(t):
            continue
        # linija so premalu bukvi nasproti simboli
        bukvi = sum(ch.isalpha() for ch in t)
        if bukvi and (bukvi / max(len(t), 1)) < 0.35 and len(t) < 40:
            continue
        redovi.append(t)
    tekst = "\n".join(redovi)
    tekst = re.sub(r"\n{3,}", "\n\n", tekst)
    return tekst.strip()


def page_image_coverage(page) -> float:
    """Kolku od površinata na stranicata e pokriena so vmetnati sliki (0–1)."""
    try:
        rect = page.rect
        page_area = abs(rect.width * rect.height) or 1.0
        images = page.get_images(full=True)
        if not images:
            return 0.0
        pokrito = 0.0
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = bbox
            pokrito += abs((x1 - x0) * (y1 - y0))
        return min(1.0, pokrito / page_area)
    except Exception as greska:
        logger.debug("Coverage на слика неуспешно: %s", greska)
        return 0.0


def treba_ocr(surov_tekst: str, coverage: float) -> bool:
    if not settings.use_ocr:
        return False
    if len(surov_tekst.strip()) < settings.ocr_min_chars:
        return True
    return coverage >= settings.ocr_image_min_coverage


def treba_pregled(izvor: str, tekst: str) -> bool:
    """1A: dokumenti so lični iminja ne odat avtomatski vo Qdrant."""
    if not settings.ocr_quarantine_pii:
        return False
    ime = Path(izvor).name
    if _QUARANTINE_NAME.search(ime) or _QUARANTINE_NAME.search(izvor):
        return True
    # mnogu linii što ličat na „Име Презиме“ = spisok
    pogodak = len(_PII_NAME_LINE.findall(tekst[:8000]))
    return pogodak >= 8


def zapisi_za_pregled(izvor: str, tekst: str, meta: dict | None = None) -> Path:
    safe = re.sub(r"[^\w.\-]+", "_", izvor, flags=re.UNICODE)[:180]
    dest = review_dir() / f"{safe}.txt"
    info = review_dir() / f"{safe}.meta.json"
    dest.write_text(tekst, encoding="utf-8")
    payload = {"source": izvor, "chars": len(tekst), **(meta or {})}
    info.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.warning(
        "Карантин (лични податоци): '%s' → %s — не се запишува во Qdrant до рачен преглед",
        izvor,
        dest,
    )
    return dest


def zabelezi_neuspeh(name: str, page_no: int, doverba: float) -> None:
    logger.warning(
        "Нечитлива страница %d во '%s' (доверба %.0f) — рачна проверка",
        page_no,
        name,
        doverba,
    )
    try:
        with open(failed_log_path(), "a", encoding="utf-8") as f:
            f.write(f"{name}\tстр.{page_no}\tдоверба={doverba:.0f}\n")
    except OSError:
        pass
