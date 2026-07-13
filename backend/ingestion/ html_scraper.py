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
   
    def __init__(self) -> None:
        self.chunks = 0
        self.sources_ok = 0
        self.failures: list[tuple[str, str]] = []

    def ok(self, n_chunks: int) -> None:
        self.chunks += n_chunks
        self.sources_ok += 1

    def fail(self, source: str, reason: str) -> None:
        self.failures.append((source, reason))
        logger.error("Неуспех за %s: %s", source, reason)

def _stable_id(source: str, index: int, text: str) -> str:
    h = hashlib.sha256(f"{source}:{index}:{text}".encode("utf-8")).hexdigest()
    return str(uuid.UUID(h[:32]))

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: очекуван mapping на највисоко ниво")
    return data

def _load_pdf_manifest() -> dict[str, dict]:
    if not PDF_MANIFEST.exists():
        return {}
    try:
        cfg = _load_yaml(PDF_MANIFEST)
    except (yaml.YAMLError, ValueError) as e:
        logger.warning("Невалиден %s — игнориран: %s", PDF_MANIFEST.name, e)
        return {}
    manifest = {}
    for item in cfg.get("pdfs", []):
        if isinstance(item, dict) and item.get("file"):
            manifest[item["file"]] = item
        else:
            logger.warning("Прескокнат невалиден запис во pdfs.yaml: %r", item)
    return manifest

def _push(chunks: list[Chunk], source: str, dry_run: bool) -> int:
    if not chunks:
        return 0
    if dry_run:
        logger.info("[dry-run] %s: %d парчиња (не се запишани)", source, len(chunks))
        return len(chunks)
    ts = _now()
    texts, metas, ids = [], [], []
    for i, c in enumerate(chunks):
        c.metadata["ingested_at"] = ts
        texts.append(c.text)
        metas.append(c.metadata)
        ids.append(_stable_id(source, i, c.text))
    upsert_chunks(texts, metas, ids)
    return len(chunks)

def _replace_source(chunks: list[Chunk], source: str, dry_run: bool) -> int:
    if not chunks:
        logger.warning("%s: 0 парчиња — старите податоци остануваат недопрени", source)
        return 0
    if not dry_run:
        delete_by_source(source)
    return _push(chunks, source, dry_run)

def ingest_pdfs(stats: Stats, dry_run: bool) -> None:
    if not PDF_DIR.exists():
        logger.warning("Нема папка %s", PDF_DIR)
        return
    manifest = _load_pdf_manifest()
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        logger.warning("Нема PDF фајлови во %s", PDF_DIR)
    for pdf in pdf_files:
        source = pdf.name
        try:
            meta = manifest.get(source, {})
            text = load_pdf(pdf)
            chunks = chunk_document(
                text, source=source, doc_type="pdf",
                title=meta.get("title") or source, url=meta.get("url"),
            )
            n = _push(chunks, source, dry_run)
            stats.ok(n)
            logger.info("[+] %s: %d парчиња", source, n)
        except Exception as e:  # noqa: BLE001 — изолирај грешка по фајл
            stats.fail(source, str(e))

def _ingest_crawled_pdf(url: str, data: bytes, stats: Stats, dry_run: bool) -> None:
    try:
        text = load_pdf_bytes(data, name=url)
        title = Path(url.split("?")[0]).name or url
        chunks = chunk_document(text, source=url, doc_type="pdf", title=title, url=url)
        n = _replace_source(chunks, url, dry_run)
        stats.ok(n)
        logger.info("[+] (pdf) %s: %d парчиња", url, n)
    except PdfError as e:
        stats.fail(url, str(e))


def _ingest_page(url: str, title: str, text: str, stats: Stats, dry_run: bool) -> None:
    chunks = chunk_document(text, source=url, doc_type="web", title=title, url=url)
    n = _replace_source(chunks, url, dry_run)
    stats.ok(n)
    logger.info("[+] %s: %d парчиња", title, n)


def ingest_web(stats: Stats, dry_run: bool) -> None:
    if not SOURCES_YAML.exists():
        logger.warning("Нема %s", SOURCES_YAML)
        return
    try:
        cfg = _load_yaml(SOURCES_YAML)
    except (yaml.YAMLError, ValueError) as e:
        stats.fail(SOURCES_YAML.name, f"невалиден YAML: {e}")
        return

    for src in cfg.get("web_sources", []):
        if not isinstance(src, dict) or not src.get("url"):
            stats.fail("sources.yaml", f"невалиден запис (нема url): {src!r}")
            continue
        url = str(src["url"]).strip()
        title = src.get("title") or url

        try:
            if url.split("?")[0].lower().endswith(".pdf"):
                # директен PDF линк во sources.yaml
                data = download_pdf(url)
                text = load_pdf_bytes(data, name=url)
                chunks = chunk_document(text, source=url, doc_type="pdf",
                                        title=title, url=url)
                n = _replace_source(chunks, url, dry_run)
                stats.ok(n)
                logger.info("[+] (pdf) %s: %d парчиња", title, n)
            elif src.get("crawl"):
                result = crawl(
                    url,
                    max_depth=int(src.get("max_depth", DEFAULT_CRAWL_DEPTH)),
                    max_pages=int(src.get("max_pages", DEFAULT_CRAWL_PAGES)),
                    fetch_pdfs=bool(src.get("fetch_pdfs", True)),
                )
                for page in result.pages:
                    page_title = page.title if page.url != url else title
                    _ingest_page(page.url, page_title, page.text, stats, dry_run)
                for pdf_url, data in result.pdfs.items():
                    _ingest_crawled_pdf(pdf_url, data, stats, dry_run)
                for bad_url, reason in result.errors.items():
                    logger.warning("Прескокнато при crawl: %s (%s)", bad_url, reason)
            else:
                text = scrape_url(url)
                _ingest_page(url, title, text, stats, dry_run)
        except Exception as e:  # noqa: BLE001 — изолирај грешка по извор
            stats.fail(url, str(e))

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["pdf", "web"])
    ap.add_argument("--dry-run", action="store_true", help="scrape + chunk без пишување во Qdrant")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stats = Stats()
    if not args.dry_run:
        ensure_collection()

    if args.only in (None, "pdf"):
        ingest_pdfs(stats, args.dry_run)
    if args.only in (None, "web"):
        ingest_web(stats, args.dry_run)

    logger.info("Вкупно %d парчиња од %d извори во '%s' (hybrid=%s)%s", stats.chunks, stats.sources_ok, settings.qdrant_collection, settings.use_hybrid, " [dry-run]" if args.dry_run else "")
    if stats.failures:
        logger.error("Неуспешни извори (%d):", len(stats.failures))
        for source, reason in stats.failures:
            logger.error("  - %s: %s", source, reason)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
