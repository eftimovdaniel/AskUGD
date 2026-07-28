from __future__ import annotations
import logging
from dataclasses import dataclass, field
import pdfplumber                                          # biblioteka za citanje tabeli od PDF, gi gleda koordinatite na tabelata

logger = logging.getLogger(__name__)

@dataclass 
class TableBlock:   # edna izvlecena tabela (spoena ako se prelevala preku stranici)
    text: str   # cist tekst na tabelata 
    section: str  # naslov/sekcija 
    page_start: int     # prva stranica
    page_end: int        # posledna stranica
    n_rows: int          # broj redovi so podatoci
    metadata: dict = field(default_factory=dict)           # dopolnitelna metadata (metod na vadenje...)

def _clean_row(red: list) -> list[str]:  # cisti eden red: trgni prazni/None kelii, spoj novi linii
    iscisteni = []
    for kelija in red:  # pomini niz sekoja kelija
        if kelija is None:    # prazna kelija (pdfplumber vrakja None za praznini)
            continue
        vrednost = str(kelija).replace("\n", " ").strip()  # spoj novi linii vo edna, trgni prazni mesta
        if vrednost:     # dodaj samo ako ostana nesto
            iscisteni.append(vrednost)
    return iscisteni

def _is_header_row(iscisten_red: list[str]) -> bool:       # pogodi dali redot e ZAGLAVIE (a ne podatoci)
    spoeno = " ".join(iscisten_red).lower()         # spoj gi keliite vo eden string, mali bukvi
    kluci = ("ред. бр", "ред.бр","намена", "износ", "шифра", "рок", "датум", "активност", "назив на предмет", "семестар", "ектс" )  # tipicni zaglavni zborovi
    return sum(1 for k in kluci if k in spoeno) >= 2       # zaglavie ako sodrzi barem 2 klucni zbora

def _row_to_text(iscisten_red: list[str], zaglavie: list[str]) -> str:  # pretvori red vo citliva linija
    kelii = iscisten_red[:]                                # kopija za da ne go menuvame originalot
    if kelii and kelii[0].replace(".", "").isdigit() and len(kelii[0]) <= 3:  # ako prva kelija e samo reden broj (1, 10)
        kelii = kelii[1:]    # trgni go (ne nosi znacenje)
    if not kelii:
        return ""
    smisleno_zaglavie = [z for z in zaglavie  if not z.lower().startswith(("ред", "бр"))]              # zaglavie bez 'ред'/'бр' koloni (tie ne se korisni)
    if smisleno_zaglavie and len(smisleno_zaglavie) == len(kelii):  # ako zaglavieto se sovpaga po broj kelii
        parovi = [f"{ime}: {vred}" for ime, vred in zip(smisleno_zaglavie, kelii)]  # napravi key: value parovi
        return " | ".join(parovi)
    return " — ".join(kelii)    # inaku samo spoj gi vrednostite citlivo

def _find_section(page) -> str: # zemi go tekstot NAD tabelata kako naslov na sekcijata
    try:
        tekst = page.extract_text() or ""
        linii = [l.strip() for l in tekst.splitlines() if l.strip()]  
        for linija in linii[:5]:  # pogledni gi prvite 5 linii
            if 3 <= len(linija.split()) <= 10 and sum(c.isdigit() for c in linija) < 4:  # kratka, bez mnogu cifri
                return linija # verojatno naslov
    except Exception: 
        pass
    return "?"

def extract_tables(pdf_path, source: str) -> list[TableBlock]:  # GLAVNA: vadi site tabeli, spojuva, pretvora vo tekst
    blokovi: list[TableBlock] = []   # gotovi tabeli-blokovi
    tekoven: dict | None = None  # tabela sto momentalno ja gradime (za spojuvanje)
    posledno_zaglavie: list[str] = []   # posledno videno zaglavie (za nasleduvanje)
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as greshka: 
        logger.warning("pdfplumber ne moze da otvori %s: %s", source, greshka)
        return []
    with pdf:   # `with` avtomatski go zatvora PDF-ot
        for br_stranica, page in enumerate(pdf.pages, 1):  # pomini niz sekoja stranica (od 1)
            try:
                surovi_tabeli = page.extract_tables()      # izvadi gi site tabeli na stranicata
            except Exception as greshka:  
                logger.warning("Tabela na str. %d (%s) padna: %s", br_stranica, source, greshka)
                continue
            for surova in surovi_tabeli:                   # pomini niz sekoja tabela na stranicata
                iscisteni = [_clean_row(r) for r in surova]  # iscisti gi site redovi
                iscisteni = [r for r in iscisteni if r]    # trgni sosema prazni redovi
                if not iscisteni:
                    continue
                zaglavie: list[str] = []
                data_start = 0
                for i, r in enumerate(iscisteni[:4]):
                    if _is_header_row(r):
                        zaglavie = r
                        data_start = i + 1
                        break
                data_redovi = iscisteni[data_start:]      
                ima_zaglavie = bool(zaglavie)
                if not ima_zaglavie and tekoven is not None:
                    zaglavie = posledno_zaglavie
                    tekoven["data"].extend(data_redovi)
                    tekoven["page_end"] = br_stranica
                    continue
                # nova tabela — zatvori ja prethodnata ako ja imase
                if tekoven is not None:
                    blokovi.append(_zavrsi(tekoven, source, posledno_zaglavie))
                sekcija = _find_section(page)
                tekoven = {"data": data_redovi, "page_start": br_stranica,
                           "page_end": br_stranica, "section": sekcija}
                posledno_zaglavie = zaglavie
    if tekoven is not None:                                # zatvori ja poslednata otvorena tabela
        blokovi.append(_zavrsi(tekoven, source, posledno_zaglavie))
    return [b for b in blokovi if b.n_rows > 0]            # vrati samo tabeli so podatoci

def _zavrsi(tekoven: dict, source: str, zaglavie: list[str]) -> TableBlock:  # pretvori sobrana tabela vo TableBlock
    linii = [_row_to_text(r, zaglavie) for r in tekoven["data"]]  # sekoj red =  citliva linija
    linii = [l for l in linii if l]                       # trgni prazni
    naslov = f"[{tekoven['section']}, стр. {tekoven['page_start']}"  # POPRAVKA: page_start, i bez dvoen ]
    if tekoven["page_end"] != tekoven["page_start"]:      
        naslov += f"–{tekoven['page_end']}"
    naslov += "]"
    tekst = naslov + "\n" + "\n".join(linii)               # naslov + site redovi
    return TableBlock(
        text=tekst,
        section=tekoven["section"],
        page_start=tekoven["page_start"],
        page_end=tekoven["page_end"],
        n_rows=len(linii),
        metadata={"extraction_method": "pdfplumber"},
    )