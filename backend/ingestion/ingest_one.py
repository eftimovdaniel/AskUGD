
from __future__ import annotations
import sys
from pathlib import Path
from ingestion.run_ingestion import ( PDF_DIR, _load_pdf_manifest, _push, _parchinja_od_tabeli,)
from ingestion.pdf_loader import load_pdf
from ingestion.chunker import chunk_document

def ingest_one(pdf_path: Path, dry_run: bool) -> None:
    pdf = pdf_path.resolve()                     # apsolutna pateka do fajlot
    if not pdf.exists():                         # dokolku fajlot ne postoi
        print(f"НЕ постои: {pdf}")
        return
    manifest = _load_pdf_manifest()              # naslov/link manifest (ako ima)
    try:
        izvor = str(pdf.relative_to(PDF_DIR.resolve()))   # izvor = relativna pateka vo data/pdfs
    except ValueError:
        izvor = pdf.name                         # ako e nadvor od data/pdfs, koristi go imeto
    meta = manifest.get(izvor, {}) or manifest.get(pdf.name, {})   # metapodatoci od manifest

    tekst = load_pdf(pdf)                         # izvlekuvanje na tekstot od pdf
    parchinja = chunk_document(                   # sechenje na parchinja
        tekst, source=izvor, doc_type="pdf",
        title=meta.get("title") or pdf.stem, url=meta.get("url"),
    )
    for parche in parchinja:
        parche.metadata.setdefault("content_type", "prose")
    if meta.get("tables", True):                 # i tabelite (ako gi ima)
        parchinja += _parchinja_od_tabeli(pdf, izvor, meta)

    try:                                         # struktura na papkite -> metadata (ciklus/fakultet)
        delovi = pdf.relative_to(PDF_DIR.resolve()).parts[:-1]
        for parche in parchinja:
            if len(delovi) >= 1:
                parche.metadata["ciklus"] = delovi[0]
            if len(delovi) >= 3:
                parche.metadata["fakultet"] = delovi[2]
    except ValueError:
        pass

    broj = _push(parchinja, izvor, dry_run)      # zapis vo Qdrant (ili proba pri dry-run)
    print(f"{izvor}: {broj} парчиња {'(dry-run, не запишани)' if dry_run else 'запишани во Qdrant'}")

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    pdfs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pdfs:
        print('Дај патека до PDF. Пример:\n  python -m ingestion.ingest_one "data/pdfs/vtor ciklus/upis_vtor_2026_27.pdf"')
        sys.exit(1)
    for p in pdfs:
        ingest_one(Path(p), dry)
