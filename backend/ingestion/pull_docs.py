# Vlece dokumenti od DOC_API_URL i gi zacuvuva kako PDF vo data/pdfs/from_api/.
# Ne pišuwa vo Qdrant — samo download. Posle mozes: run_ingestion --only pdf
#
# Primer:
#   export DOC_API_URL=https://api.primer.mk
#   export DOC_API_TOKEN=...
#   python -m ingestion.pull_docs
#   python -m ingestion.pull_docs --since 2026-10-01T00:00:00Z
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from ingestion.doc_api import DocApiClient, DocApiError

logger = logging.getLogger("pull_docs")

_BACKEND = Path(__file__).resolve().parent.parent
_OUT_DIR = _BACKEND / "data" / "pdfs" / "from_api"


def _bezbedno_ime(doc_id: str, title: str) -> str:
    baza = re.sub(r"[^\w.\-]+", "_", f"{doc_id}_{title}", flags=re.UNICODE).strip("_")
    if not baza.lower().endswith(".pdf"):
        baza += ".pdf"
    return baza[:180] or f"{doc_id}.pdf"


def main() -> int:
    ap = argparse.ArgumentParser(description="Vleci PDF dokumenti od uni Document API")
    ap.add_argument(
        "--since",
        default=None,
        help="ISO vreme: samo dokumenti updated_since=... (npr. 2026-10-01T00:00:00Z)",
    )
    ap.add_argument(
        "--out",
        default=str(_OUT_DIR),
        help="Papka kade da se zacuvat PDF (default: data/pdfs/from_api)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        klient = DocApiClient()
        dokumenti = klient.list_documents(updated_since=args.since)
    except DocApiError as e:
        logger.error("%s", e)
        return 1

    logger.info("Najdeni %d dokument(i)", len(dokumenti))
    ok = 0
    fail = 0
    for doc in dokumenti:
        ime = _bezbedno_ime(doc.id, doc.title)
        pateka = out / ime
        try:
            bajti = klient.download_file(doc)
            pateka.write_bytes(bajti)
            ok += 1
            logger.info("[+] %s → %s (%d bajti)", doc.id, pateka.name, len(bajti))
        except DocApiError as e:
            fail += 1
            logger.error("[-] %s: %s", doc.id, e)

    try:
        izbrisani = klient.list_deleted(since=args.since)
        if izbrisani:
            logger.info("Izbrisani kaj izvorot (%d): %s", len(izbrisani), ", ".join(izbrisani[:20]))
    except DocApiError as e:
        logger.warning("list_deleted ne uspea (OK ako endpoint uste go nema): %s", e)

    logger.info("Gotovo: %d OK, %d fail → %s", ok, fail, out)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
