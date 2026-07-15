"""Главен ingestion скрипт: PDF-ови + HTML/crawl извори -> parchinja -> Qdrant.

Употреба:
    python -m ingestion.run_ingestion               # сè (PDF + web)
    python -m ingestion.run_ingestion --only pdf
    python -m ingestion.run_ingestion --only web    # за scheduled refresh
    python -m ingestion.run_ingestion --dry-run     # без пишување во базата

podatoci/sources.yaml — по извор:
    web_sources:
      - adresa: https://www.ugd.edu.mk/studenti/
        naslov: Студентски информации
        crawl: true          # следи линкови на истиот домен (депт 1)
        max_depth: 1         # опц.
        max_pages: 30        # опц.
        fetch_pdfs: true     # опц. — преземи PDF-ови најдени на страниците

Гаранции:
- Идемпотентно: ID на секое парче е детерминистички hash — нема дупликати.
- Без загуба на податоци: старите парчиња за URL се бришат ДУРИ откако
  новото scrape-ирање и parche-ирање ќе успее.
- Грешка кај еден извор/фајл не го прекинува остатокот; на крај има извештај
  и излезен код != 0 ако имало неуспеси.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.config import settings
from app.core.vectorstore import ensure_collection, upsert_chunks, delete_by_source
from ingestion.chunker import Chunk, chunk_document
from ingestion.html_scraper import crawl, download_pdf, scrape_url
from ingestion.pdf_loader import PdfError, load_pdf, load_pdf_bytes

logger = logging.getLogger("ingestion")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PDF_DIR = DATA_DIR / "pdfs"
SOURCES_YAML = DATA_DIR / "sources.yaml"
PDF_MANIFEST = DATA_DIR / "pdfs.yaml"

DEFAULT_CRAWL_DEPTH = 1
DEFAULT_CRAWL_PAGES = 30


class Stats:
    """Броење на успеси/неуспеси за финален извештај и exit code."""

    def __init__(self) -> None:
        self.chunks = 0
        self.sources_ok = 0
        self.failures: list[tuple[str, str]] = []

    def ok(self, broj_parchinja: int) -> None:
        self.chunks += broj_parchinja
        self.sources_ok += 1

    def fail(self, izvor: str, pricina: str) -> None:
        self.failures.append((izvor, pricina))
        logger.error("Неуспех за %s: %s", izvor, pricina)


def _stable_id(izvor: str, indeks: int, tekst: str) -> str:
    otpecatok = hashlib.sha256(f"{izvor}:{indeks}:{tekst}".encode("utf-8")).hexdigest()
    return str(uuid.UUID(otpecatok[:32]))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict:
    """Безбедно вчитај YAML; враќа {} при празен фајл, фрла при невалиден."""
    podatoci = yaml.safe_load(path.read_text(encoding="utf-8"))
    if podatoci is None:
        return {}
    if not isinstance(podatoci, dict):
        raise ValueError(f"{path.name}: очекуван mapping на највисоко ниво")
    return podatoci


def _load_pdf_manifest() -> dict[str, dict]:
    """Врати {filename: {naslov, adresa}} од podatoci/pdfs.yaml (толерантно на грешки)."""
    if not PDF_MANIFEST.exists():
        return {}
    try:
        konfig = _load_yaml(PDF_MANIFEST)
    except (yaml.YAMLError, ValueError) as e:
        logger.warning("Невалиден %s — игнориран: %s", PDF_MANIFEST.name, e)
        return {}
    manifest_pdf = {}
    for element in konfig.get("pdfs", []):
        if isinstance(element, dict) and element.get("file"):
            manifest_pdf[element["file"]] = element
        else:
            logger.warning("Прескокнат невалиден запис во pdfs.yaml: %r", element)
    return manifest_pdf


def _push(parchinja: list[Chunk], izvor: str, dry_run: bool) -> int:
    if not parchinja:
        return 0
    if dry_run:
        logger.info("[dry-run] %s: %d парчиња (не се запишани)", izvor, len(parchinja))
        return len(parchinja)
    vreme = _now()
    tekstovi, metadatoci, identifikatori = [], [], []
    for indeks, parche in enumerate(parchinja):
        parche.metadata["ingested_at"] = vreme
        tekstovi.append(parche.text)
        metadatoci.append(parche.metadata)
        identifikatori.append(_stable_id(izvor, indeks, parche.text))
    upsert_chunks(tekstovi, metadatoci, identifikatori)
    return len(parchinja)


def _replace_source(parchinja: list[Chunk], izvor: str, dry_run: bool) -> int:
    """Замени ги парчињата за извор БЕЗ прозорец на загуба:
    бриши стари само ако има нови подготвени парчиња."""
    if not parchinja:
        logger.warning("%s: 0 парчиња — старите податоци остануваат недопрени", izvor)
        return 0
    if not dry_run:
        delete_by_source(izvor)
    return _push(parchinja, izvor, dry_run)


# ------------------------------------------------------------------ PDF
def ingest_pdfs(statistika: Stats, dry_run: bool) -> None:
    if not PDF_DIR.exists():
        logger.warning("Нема папка %s", PDF_DIR)
        return
    manifest_pdf = _load_pdf_manifest()
    pdf_fajlovi = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_fajlovi:
        logger.warning("Нема PDF фајлови во %s", PDF_DIR)
    for pdf in pdf_fajlovi:
        izvor = pdf.name
        try:
            meta_zapis = manifest_pdf.get(izvor, {})
            tekst = load_pdf(pdf)
            parchinja = chunk_document(
                tekst, source=izvor, doc_type="pdf",
                title=meta_zapis.get("title") or izvor, url=meta_zapis.get("url"),
            )
            broj_parchinja = _push(parchinja, izvor, dry_run)
            statistika.ok(broj_parchinja)
            logger.info("[+] %s: %d парчиња", izvor, broj_parchinja)
        except Exception as greshka:  # noqa: BLE001 — изолирај грешка по фајл
            statistika.fail(izvor, str(greshka))


# ------------------------------------------------------------------ Web
def _ingest_crawled_pdf(adresa: str, podatoci: bytes, statistika: Stats, dry_run: bool) -> None:
    try:
        tekst = load_pdf_bytes(podatoci, name=adresa)
        naslov = Path(adresa.split("?")[0]).name or adresa
        parchinja = chunk_document(tekst, source=adresa, doc_type="pdf", title=naslov, url=adresa)
        broj_parchinja = _replace_source(parchinja, adresa, dry_run)
        statistika.ok(broj_parchinja)
        logger.info("[+] (pdf) %s: %d парчиња", adresa, broj_parchinja)
    except PdfError as greshka:
        statistika.fail(adresa, str(greshka))


def _ingest_page(adresa: str, naslov: str, tekst: str, statistika: Stats, dry_run: bool) -> None:
    parchinja = chunk_document(tekst, source=adresa, doc_type="web", title=naslov, url=adresa)
    broj_parchinja = _replace_source(parchinja, adresa, dry_run)
    statistika.ok(broj_parchinja)
    logger.info("[+] %s: %d парчиња", naslov, broj_parchinja)


def ingest_web(statistika: Stats, dry_run: bool) -> None:
    if not SOURCES_YAML.exists():
        logger.warning("Нема %s", SOURCES_YAML)
        return
    try:
        konfig = _load_yaml(SOURCES_YAML)
    except (yaml.YAMLError, ValueError) as greshka:
        statistika.fail(SOURCES_YAML.name, f"невалиден YAML: {greshka}")
        return

    for zapis in konfig.get("web_sources", []):
        if not isinstance(zapis, dict) or not zapis.get("url"):
            statistika.fail("sources.yaml", f"невалиден запис (нема adresa): {zapis!r}")
            continue
        adresa = str(zapis["url"]).strip()
        naslov = zapis.get("title") or adresa

        try:
            if adresa.split("?")[0].lower().endswith(".pdf"):
                # директен PDF линк во sources.yaml
                podatoci = download_pdf(adresa)
                tekst = load_pdf_bytes(podatoci, name=adresa)
                parchinja = chunk_document(tekst, source=adresa, doc_type="pdf",
                                        title=naslov, url=adresa)
                broj_parchinja = _replace_source(parchinja, adresa, dry_run)
                statistika.ok(broj_parchinja)
                logger.info("[+] (pdf) %s: %d парчиња", naslov, broj_parchinja)
            elif zapis.get("crawl"):
                rezultat = crawl(
                    adresa,
                    max_depth=int(zapis.get("max_depth", DEFAULT_CRAWL_DEPTH)),
                    max_pages=int(zapis.get("max_pages", DEFAULT_CRAWL_PAGES)),
                    fetch_pdfs=bool(zapis.get("fetch_pdfs", True)),
                )
                for stranica in rezultat.pages:
                    naslov_stranica = stranica.title if stranica.url != adresa else naslov
                    _ingest_page(stranica.url, naslov_stranica, stranica.text, statistika, dry_run)
                for pdf_adresa, podatoci in rezultat.pdfs.items():
                    _ingest_crawled_pdf(pdf_adresa, podatoci, statistika, dry_run)
                for losha_adresa, pricina in rezultat.errors.items():
                    logger.warning("Прескокнато при crawl: %s (%s)", losha_adresa, pricina)
            else:
                tekst = scrape_url(adresa)
                _ingest_page(adresa, naslov, tekst, statistika, dry_run)
        except Exception as greshka:  # noqa: BLE001 — изолирај грешка по извор
            statistika.fail(adresa, str(greshka))


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["pdf", "web"])
    ap.add_argument("--dry-run", action="store_true",
                    help="scrape + parche без пишување во Qdrant")
    ap.add_argument("-v", "--verbose", action="store_true")
    argumenti = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if argumenti.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    statistika = Stats()
    if not argumenti.dry_run:
        ensure_collection()

    if argumenti.only in (None, "pdf"):
        ingest_pdfs(statistika, argumenti.dry_run)
    if argumenti.only in (None, "web"):
        ingest_web(statistika, argumenti.dry_run)

    logger.info("Вкупно %d парчиња од %d извори во '%s' (hybrid=%s)%s",
                statistika.chunks, statistika.sources_ok, settings.qdrant_collection,
                settings.use_hybrid, " [dry-run]" if argumenti.dry_run else "")
    if statistika.failures:
        logger.error("Неуспешни извори (%d):", len(statistika.failures))
        for izvor, pricina in statistika.failures:
            logger.error("  - %s: %s", izvor, pricina)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
