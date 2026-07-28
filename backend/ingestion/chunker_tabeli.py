from __future__ import annotations
import re
from dataclasses import dataclass, field

TABLE_MAX_WORDS = 350
TABLE_MIN_ROWS = 1
_PODNASLOV_RE = re.compile(r"^—\s*(.+?)\s*—$")
_MAKS_ZBOROVI_PODNASLOV = 10
_NASLOV_RE = re.compile(r"^\[.*\]$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)

def _zaglavna_linija(koloni: list[str]) -> str:
    if not koloni:
        return ""
    return "Колони: " + ", ".join(koloni)

def _iseci_dolg_red(red: str, maks_zborovi: int) -> list[str]:
    zborovi = red.split()
    if len(zborovi) <= maks_zborovi:
        return [red]
    if " | " in red:
        prefiks = red.split(" | ", 1)[0]
    else:
        prefiks = " ".join(zborovi[:8])
    prefiks = " ".join(prefiks.split()[:12])
    rezerva = len(prefiks.split()) + 2
    cekor = max(20, maks_zborovi - rezerva)
    parcinja = []
    for pocetok in range(0, len(zborovi), cekor):
        parche = " ".join(zborovi[pocetok:pocetok + cekor])
        parcinja.append(parche if pocetok == 0 else f"{prefiks} (продолжение): {parche}")
    return parcinja

def _presmetaj_delovi(redovi: list[str], maks_zborovi: int) -> list[list[str]]:
    delovi: list[list[str]] = []
    tekoven: list[str] = []
    broj_zborovi = 0
    for surov_red in redovi:
        for red in _iseci_dolg_red(surov_red, maks_zborovi):
            zborovi_red = len(red.split())
            if broj_zborovi + zborovi_red > maks_zborovi and tekoven:
                delovi.append(tekoven)
                tekoven, broj_zborovi = [], 0
            tekoven.append(red)
            broj_zborovi += zborovi_red
    if tekoven:
        delovi.append(tekoven)
    return delovi

def _posleden_podnaslov(redovi: list[str]) -> str | None:
    for red in reversed(redovi):
        sovpaganje = _PODNASLOV_RE.match(red)
        if sovpaganje:
            kandidat = sovpaganje.group(1).strip()
            if len(kandidat.split()) <= _MAKS_ZBOROVI_PODNASLOV:
                return kandidat
    return None

def chunk_table_blocks(blokovi,source: str,doc_type: str = "pdf",title: str | None = None,url: str | None = None,lang: str = "mk",neutralize=None,) -> list[Chunk]:
    rezultat: list[Chunk] = []
    for tabela_br, blok in enumerate(blokovi):
        site_linii = [l for l in blok.text.splitlines() if l.strip()]
        if not site_linii:
            continue
        if _NASLOV_RE.match(site_linii[0]):
            naslov_linija, redovi = site_linii[0], site_linii[1:]
        else:
            naslov_linija, redovi = "", site_linii
        if len(redovi) < TABLE_MIN_ROWS:
            continue
        zaglavje = _zaglavna_linija(blok.columns)
        rezerva = (len((naslov_linija + " " + zaglavje).split())+ _MAKS_ZBOROVI_PODNASLOV + 3)
        buxhet = max(50, TABLE_MAX_WORDS - rezerva)
        delovi = _presmetaj_delovi(redovi, buxhet)
        vkupno_delovi = len(delovi)
        prenesen_podnaslov: str | None = None
        for del_br, del_redovi in enumerate(delovi):
            glava = [linija for linija in (naslov_linija, zaglavje) if linija]
            if del_br > 0 and prenesen_podnaslov:
                glava.append(f"— {prenesen_podnaslov} (продолжение) —")
            tekst = "\n".join(glava + del_redovi)
            tekst = _CONTROL_RE.sub("", tekst)
            if neutralize is not None:
                tekst = neutralize(tekst)
            rezultat.append(
                Chunk(
                    tekst,
                    {
                        "source": source,
                        "title": title or source,
                        "url": url,
                        "doc_type": doc_type,
                        "lang": lang,
                        "chunk_index": len(rezultat),
                        "content_type": "table",
                        "strategy": "table",
                        "section": blok.section,
                        "columns": blok.columns,
                        "page_start": blok.page_start,
                        "page_end": blok.page_end,
                        "table_index": tabela_br,
                        "part": del_br,
                        "n_parts": vkupno_delovi,
                        "n_rows": len(del_redovi),
                        "word_count": len(tekst.split()),
                        "extraction_method": blok.metadata.get(
                            "extraction_method", "pdfplumber"
                        ),
                    },
                )
            )
            nov = _posleden_podnaslov(del_redovi)
            if nov:
                prenesen_podnaslov = nov
    return rezultat
