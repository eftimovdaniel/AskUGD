from __future__ import annotations
import re
from dataclasses import dataclass, field

ARTICLE_RE = re.compile(r"(?m)^\s*(Член\s+\d+[а-я]?)\b")
MAX_WORDS = 1000
OVERLAP_RATIO = 0.15         
PARAGRAPH_TARGET = 800
MIN_CHUNK_WORDS = 8

_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"disregard\s+(the\s+)?(above|previous|prior)|"
    r"forget\s+(all\s+)?(previous|prior)\s+instructions?|"
    r"you\s+are\s+now\b|act\s+as\s+(a|an)\b|pretend\s+to\s+be\b|"
    r"new\s+instructions?\s*:|system\s*prompt|developer\s+message|"
    r"do\s+not\s+follow\s+the\s+system|reveal\s+your\s+(instructions|prompt)|"
    r"игнорирај\s+ги\s+(претходните|инструкциите|горните)|"
    r"заборави\s+ги\s+претходните|нови\s+инструкции\s*:|"
    r"системски\s+промпт|однесувај\s+се\s+како)"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)

def neutralize_injections(text: str) -> str:
    return _INJECTION_RE.sub("[отстранета инструкција]", text)

def _split_by_words(text: str, maks_zborovi: int = MAX_WORDS) -> list[str]:
    zborovi = text.split()
    if len(zborovi) <= maks_zborovi:
        return [text]
    preklop = max(0, int(maks_zborovi * OVERLAP_RATIO))
    cekor = max(1, maks_zborovi - preklop)
    delovi, pozicija = [], 0
    while pozicija < len(zborovi):
        delovi.append(" ".join(zborovi[pozicija:pozicija + maks_zborovi]))
        if pozicija + maks_zborovi >= len(zborovi):
            break
        pozicija += cekor
    return delovi

def _chunk_by_articles(text: str) -> list[Chunk]:
    sovpaganja = list(ARTICLE_RE.finditer(text))
    parchinja: list[Chunk] = []
    if sovpaganja and sovpaganja[0].start() > 0:
        voved = text[:sovpaganja[0].start()].strip()
        if len(voved.split()) > 20:
            for del_br, delce in enumerate(_split_by_words(voved)):
                parchinja.append(Chunk(delce, {"article_no": None, "section": "вовед", "part": del_br}))
    for indeks_sovp, sovpaganje in enumerate(sovpaganja):
        pocetok = sovpaganje.start()
        kraj = (sovpaganja[indeks_sovp + 1].start()
               if indeks_sovp + 1 < len(sovpaganja) else len(text))
        telo = text[pocetok:kraj].strip()
        oznaka = sovpaganje.group(1).strip()
        for del_br, delce in enumerate(_split_by_words(telo)):
            parchinja.append(Chunk(delce, {"article_no": oznaka, "part": del_br}))
    return parchinja

def _chunk_by_paragraphs(text: str) -> list[Chunk]:
    surovi_pasusi = [pasus_edinica.strip() for pasus_edinica in text.split("\n\n") if pasus_edinica.strip()]
    pasusi: list[str] = []
    for pasus_edinica in surovi_pasusi:
        pasusi.extend(_split_by_words(pasus_edinica))  # ниту еден пасус да не е џин

    parchinja: list[Chunk] = []
    bafer: list[str] = []
    broj_zborovi, sekcija_br = 0, 0
    for pasus in pasusi:
        zborovi_pasus = len(pasus.split())
        if broj_zborovi + zborovi_pasus > PARAGRAPH_TARGET and bafer:
            parchinja.append(Chunk("\n\n".join(bafer), {"section": f"дел {sekcija_br}"}))
            sekcija_br += 1
            posleden_pasus = bafer[-1]
            if len(posleden_pasus.split()) <= PARAGRAPH_TARGET // 2:
                bafer = [posleden_pasus]
                broj_zborovi = len(posleden_pasus.split())
            else:
                bafer, broj_zborovi = [], 0
        bafer.append(pasus)
        broj_zborovi += zborovi_pasus
    if bafer:
        parchinja.append(Chunk("\n\n".join(bafer), {"section": f"дел {sekcija_br}"}))
    return parchinja

def chunk_document(text: str, source: str, doc_type: str = "pdf", title: str | None = None, url: str | None = None, lang: str = "mk",) -> list[Chunk]:
    if not text or not text.strip():
        return []
    text = _CONTROL_RE.sub("", text)
    ima_clenovi = len(ARTICLE_RE.findall(text)) >= 3
    parchinja = _chunk_by_articles(text) if ima_clenovi else _chunk_by_paragraphs(text)
    rezultat: list[Chunk] = []
    for parche in parchinja:
        if len(parche.text.split()) < MIN_CHUNK_WORDS:
            continue
        parche.text = neutralize_injections(parche.text)   
        parche.metadata.update({
            "source": source,
            "title": title or source,
            "url": url,
            "doc_type": doc_type,
            "lang": lang,
            "chunk_index": len(rezultat),          
            "strategy": "article" if ima_clenovi else "paragraph",
            "word_count": len(parche.text.split()),
        })
        rezultat.append(parche)
    return rezultat
