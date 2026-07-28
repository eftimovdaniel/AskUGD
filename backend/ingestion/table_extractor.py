from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
import pdfplumber

logger = logging.getLogger(__name__)
_MIN_PREKLOP = 0.30
_MAKS_ZAGLAVNI_REDOVI = 6

@dataclass
class TableBlock:
    text: str
    section: str
    page_start: int
    page_end: int
    n_rows: int
    columns: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

def _redovi_so_pozicii(tabela) -> list[list[tuple[float, float, str]]]:
    try:
        mreza = tabela.extract()
    except Exception:
        return []
    izlez: list[list[tuple[float, float, str]]] = []
    for red_obj, red_tekst in zip(tabela.rows, mreza):
        kelii = []
        for kelija, tekst in zip(red_obj.cells, red_tekst):
            if kelija is None or not tekst:
                continue
            x0, _t, x1, _b = kelija
            cist = str(tekst).replace("\n", " ").strip()
            if cist:
                kelii.append((x0, x1, cist))
        if kelii:
            izlez.append(kelii)
    return izlez

def _preklop(a0: float, a1: float, b0: float, b1: float) -> float:
    presek = min(a1, b1) - max(a0, b0)
    if presek <= 0:
        return 0.0
    najmala_sirina = min(a1 - a0, b1 - b0) or 1.0
    return presek / najmala_sirina

def _e_red_so_podatoci(kelii: list[tuple[float, float, str]]) -> bool:
    if not kelii:
        return False
    tekstovi = [t for _, _, t in kelii]
    ima_cifra = any(any(c.isdigit() for c in t) for t in tekstovi)
    return ima_cifra

def _spoi_ime(delovi: list[str]) -> str:
    videni: list[str] = []
    for del_ in delovi:
        if del_ not in videni:
            videni.append(del_)
    zborovi, izlez = set(), []
    for zbor in " ".join(videni).split():
        if zbor.lower() not in zborovi:
            zborovi.add(zbor.lower())
            izlez.append(zbor)
    return " ".join(izlez).strip()

_MAKS_ZNACI_IME_KOLONA = 60
_MAKS_ZBOROVI_IME_KOLONA = 8

def _e_ime_na_kolona(tekst: str) -> bool:
    cist = tekst.strip()
    if not cist:
        return False
    return (len(cist) <= _MAKS_ZNACI_IME_KOLONA and len(cist.split()) <= _MAKS_ZBOROVI_IME_KOLONA)

def _spoi_zaglavie(zaglavni_redovi: list[list[tuple[float, float, str]]]) -> list[tuple[float, float, str]]:
    koloni: list[dict] = []
    for red in zaglavni_redovi:
        for x0, x1, tekst in red:
            if not _e_ime_na_kolona(tekst):
                continue
            sirina = x1 - x0
            roditel = None
            for k in koloni:
                if _preklop(x0, x1, k["x0"], k["x1"]) < _MIN_PREKLOP:
                    continue
                sirina_k = k["x1"] - k["x0"]
                if sirina < sirina_k * 0.6:
                    roditel = k
                    break
                k["delovi"].append(tekst)
                k["x0"] = min(k["x0"], x0)
                k["x1"] = max(k["x1"], x1)
                roditel = "spoena"
                break
            if roditel is None:
                koloni.append({"x0": x0, "x1": x1, "delovi": [tekst]})
            elif roditel != "spoena":
                ime_roditel = _spoi_ime(roditel["delovi"])
                koloni.append({"x0": x0, "x1": x1, "delovi": [ime_roditel, tekst]})
    koloni.sort(key=lambda k: k["x0"])
    if len(koloni) < 2:
        return []
    return [(k["x0"], k["x1"], _spoi_ime(k["delovi"])) for k in koloni]

def _red_vo_tekst(kelii: list[tuple[float, float, str]],koloni: list[tuple[float, float, str]]) -> str:
    parcinja = []
    for x0, x1, vrednost in kelii:
        najdobra, najtesna_sirina = None, float("inf")
        for kx0, kx1, ime in koloni:
            if _preklop(x0, x1, kx0, kx1) < _MIN_PREKLOP:
                continue
            sirina = kx1 - kx0
            if sirina < najtesna_sirina:
                najdobra, najtesna_sirina = ime, sirina
        najdobar_preklop = 1.0 if najdobra else 0.0
        if najdobra and najdobar_preklop >= _MIN_PREKLOP:
            if re.fullmatch(r"\d{1,3}\.?", vrednost) and "бр" in najdobra.lower():
                continue
            parcinja.append(f"{najdobra}: {vrednost}")
        else:
            parcinja.append(vrednost)
    return " | ".join(parcinja)

def _naslov_nad_tabelata(linii_na_stranica, tabela) -> str | None:
    try:
        _x0, top, _x1, _bot = tabela.bbox
        kandidati = [ linija for linija in linii_na_stranica if linija["bottom"] <= top + 2 and 0 <= top - linija["bottom"] < 60 ]
    except Exception:
        return None
    if not kandidati:
        return None
    najbliska = max(kandidati, key=lambda linija: linija["bottom"])["text"].strip()
    if not najbliska or sum(znak.isdigit() for znak in najbliska) > 8:
        return None
    return najbliska if len(najbliska) <= 120 else najbliska[:120]

def _najdi_sekcija(page, tabela=None, linii_na_stranica=None) -> str:
    if tabela is not None and linii_na_stranica:
        nad = _naslov_nad_tabelata(linii_na_stranica, tabela)
        if nad:
            return nad
    try:
        tekst = page.extract_text() or ""
        linii = [l.strip() for l in tekst.splitlines() if l.strip()]
        for linija in linii[:5]:
            if 3 <= len(linija.split()) <= 14 and sum(c.isdigit() for c in linija) < 5:
                return linija
    except Exception:
        pass
    return "?"

def _e_vistinska_tabela(tabela, redovi: list[list[tuple[float, float, str]]]) -> bool:
    if len(redovi) < 2:
        return False
    poplneti = sum(len(red) for red in redovi)
    if poplneti / len(redovi) < 2.0:
        return False
    try:
        vkupno_kelii = sum(len(red_obj.cells) for red_obj in tabela.rows)
    except Exception:
        return True
    if vkupno_kelii and poplneti / vkupno_kelii < 0.15:
        return False
    return True

def extract_tables(pdf_path, source: str = "") -> list[TableBlock]:
    blokovi: list[TableBlock] = []
    tekoven: dict | None = None
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as greshka:
        logger.warning("pdfplumber ne moze da otvori %s: %s", source, greshka)
        return []
    with pdf:
        for br_stranica, page in enumerate(pdf.pages, 1):
            try:
                tabeli = page.find_tables()
            except Exception as greshka:
                logger.warning("Tabeli na str. %d (%s) padnaa: %s",br_stranica, source, greshka)
                continue
            try:
                linii_na_stranica = page.extract_text_lines() if tabeli else []
            except Exception:
                linii_na_stranica = []
            for tabela in tabeli:
                redovi = _redovi_so_pozicii(tabela)
                if not redovi:
                    continue
                if not _e_vistinska_tabela(tabela, redovi):
                    continue
                zaglavni, data_start = [], 0
                for i, red in enumerate(redovi[:_MAKS_ZAGLAVNI_REDOVI]):
                    if _e_red_so_podatoci(red):
                        break
                    zaglavni.append(red)
                    data_start = i + 1
                data_redovi = redovi[data_start:]
                if not data_redovi:
                    continue
                koloni = _spoi_zaglavie(zaglavni) if zaglavni else []
                if not koloni and tekoven is not None:
                    tekoven["data"].extend(data_redovi)
                    tekoven["page_end"] = br_stranica
                    continue
                if tekoven is not None:
                    blokovi.append(_zavrsi(tekoven))
                tekoven = {"data": data_redovi, "koloni": koloni,
                           "page_start": br_stranica, "page_end": br_stranica,
                           "section": _najdi_sekcija(page, tabela, linii_na_stranica),
                           "source": source}
    if tekoven is not None:
        blokovi.append(_zavrsi(tekoven))
    return [b for b in blokovi if b.n_rows > 0]

def _zavrsi(tekoven: dict) -> TableBlock:
    koloni = tekoven["koloni"]
    linii = []
    imenja = {ime.lower() for _, _, ime in koloni}
    for red in tekoven["data"]:
        vrednosti = [t for _, _, t in red]
        if vrednosti and all(len(v) <= 3 and any(v.lower() in i for i in imenja) for v in vrednosti):
            continue
        if (len(red) == 1 and not any(c.isdigit() for c in red[0][2][:4]) and len(red[0][2].split()) <= 10):
            linii.append(f"— {red[0][2]} —")
            continue
        linija = _red_vo_tekst(red, koloni)
        if linija:
            linii.append(linija)
    naslov = f"[{tekoven['section']}, стр. {tekoven['page_start']}"
    if tekoven["page_end"] != tekoven["page_start"]:
        naslov += f"–{tekoven['page_end']}"
    naslov += "]"
    imenja_koloni = [ime for _, _, ime in koloni]
    return TableBlock(
        text=naslov + "\n" + "\n".join(linii),
        section=tekoven["section"],
        page_start=tekoven["page_start"],
        page_end=tekoven["page_end"],
        n_rows=len(linii),
        columns=imenja_koloni,
        metadata={"extraction_method": "pdfplumber",
                  "columns": imenja_koloni,
                  "source": tekoven.get("source", "")},
    )
