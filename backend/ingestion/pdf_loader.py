from __future__ import annotations
import logging
import re
from pathlib import Path
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 50 * 1024 * 1024   # 50 MB
MAX_PAGES = 500

#oznaki sabloni sto se pojavuvaat na site stranici od dokumentacija i ne treba da se zemat vo predvid, ne se vazni infomracii
NOISE_PATTERNS = [
    r"УНИВЕРЗИТЕТСКИ\s+ГЛАСНИК",    #univerz glasnik
    r"Број\s+\d+,\s*\w+\s+\d{4}",   #broj na glasnikot kade \s+ eden ili poveke prazni mesta\d+ = eden ili povekje cifri, \s* = mozni prazni mesta, \w+ = zbor,  \d{4} = tocno 4 cifri (godina)
    r"Ознака:\s*\S+",   #oznaka
    r"Верзија:\s*\S+",  # verzija 
    r"Страница\s*\d+\s*/\s*\d+",    #stranici dve cifri razdeleni so / i so prazni mesta pomegu niv
    r"Овој документ е сопственост.*?авторски права\.",  # dislaimer za dokumentot 
    r"Забрането е\s+фотографирање.*?запис\.",   #zabraneti se potografii zapisi za tekstot pomegu
]
_NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE | re.DOTALL) #spoj na site sabloni vo eden regex, se kompjalira ednas 

_INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]") #regex sto faka nevidlivi karakteri

class PdfError(Exception):  #klasa za greski pri vcitnuvanje na pdf
    """Грешка при вчитување PDF (безбедна порака, без стек кон корисник)."""

def clean_text(text: str) -> str:  #cistenje na sumovite,nevidlivite znaci i pazniot prostor od izvleceniot tekst, se povikuva na sekoja stranica pri nejzino vcituvanje  
    text = _NOISE_RE.sub(" ", text) #zamena na site sumovi so prazni mesta 
    text = _INVISIBLE_RE.sub("", text)  #otstranuvanje na nevidlivite karakteri celosno 
    text = text.replace("\xa0", " ")    #zamena na tvrite prostori so obicno prazno mesto
    text = "".join(znak for znak in text    #gradenje na tekstot od pocetok, samo so dozvolenite znaci
                   if znak == "\n" or znak == "\t" or ord(znak) >= 32)  
    text = re.sub(r"\n\s*\n+", "\n\n", text)   # poveketo prazni mesta se vo eden 
    text = re.sub(r"[ \t]+", " ", text)        # visok na prazni mesta 
    return text.strip() #otstranuvanje na prazni mesta/linii na pocetokot i na krajot na tekstot

def _extract(dokument: fitz.Document, name: str) -> str:   #proveruva dokumenti i vadi cist tekst od site stranici na pdf, se povikuv od load_pdf i load_pdf_bytes za da ne povtoruma kod 
    if dokument.needs_pass: #se proveruva dali pdf bara lozinka ili pak ne
        raise PdfError(f"'{name}' е заштитен со лозинка — прескокнат")  #se frla greska ne moze da se pristapi do niv
    if dokument.page_count > MAX_PAGES: #dokolku ima poveke od 500 stranici
        raise PdfError(f"'{name}' има {dokument.page_count} страници (лимит {MAX_PAGES})")  #se odbiva, pdf fajlot e predolg
    stranici: list[str] = [] #lista vo koja gi sobiram iscistenite tekstovi od sekoja stranica
    for page_no in range(dokument.page_count):  #se pominuva niz sekoja stranica po indeks od 0 do posleden 
        try:
            surov = dokument.load_page(page_no).get_text("text")   #vcituvanje na stranicata i vadenje na tekstot, so PyMuPDF se citat crtackite komandi na sekoja strana i go pretvara vo citliv string
        except Exception as greshka:  #ako edna stranica e opstetena 
            logger.warning("Прескокната страница %d во '%s': %s",page_no + 1, name, greshka)
            continue    #se prodolzuva 
        iscisten = clean_text(surov)    #cistenje na suroviot tekst izvlecen od pumypdf
        if iscisten:    #dodavanje na tekstot po cistenjeto
            stranici.append(iscisten)
    if not stranici:    #dokolku vo pdf ne e pronajden nikakov tekst 
        raise PdfError(f"'{name}' не содржи извлечлив текст")
    return "\n\n".join(stranici) #spojuvanje na izvleceniot tekst vo celina

def load_pdf(path: str | Path) -> str: #se koriste za vcituvanje na pdf dokumentite od diskot, se vika od run_ingestion za lokalnite pdf vo data/pdfs
    pateka = Path(path) #vlezot go pretvarame vo path objekt 
    if not pateka.is_file():    #dokolku ne se pronajdeni. fajlovi na navedenata lokacija
        raise PdfError(f"Фајлот не постои: {pateka.name}")
    if pateka.stat().st_size > MAX_FILE_BYTES:  #stat().st_size ja dava goleminata vo bajti, ako nadmine 50mb
        raise PdfError(f"'{pateka.name}' е поголем од {MAX_FILE_BYTES // (1024*1024)} MB")  #se odbiva, limitot se nadminuva
    try:
        with fitz.open(pateka) as dokument: #otvaranje na pdf, so with go zatvara na kraj so toa se osloboduva memorija
            return _extract(dokument, pateka.name)  #vadenje na tekstot od pdf
    except PdfError:    #ako se jave error
        raise
    except Exception as greshka:
        raise PdfError(f"Не може да се отвори '{pateka.name}': {greshka}") from greshka

def load_pdf_bytes(podatoci: bytes, name: str = "<web-pdf>") -> str:    #vcituvanje pdf od bajti vo memorijata, se koriste kaj web pdf fajlovite
    if len(podatoci) > MAX_FILE_BYTES: #proverka na goleminata vo bajti
        raise PdfError(f"'{name}' е поголем од {MAX_FILE_BYTES // (1024*1024)} MB") 
    try:
        with fitz.open(stream=podatoci, filetype="pdf") as dokument: # stream = podatoci se otvara preku bajtite vo memorijata so filetype se kazuva kade e pdf
            return _extract(dokument, name)
    except PdfError:
        raise
    except Exception as greshka:
        raise PdfError(f"Не може да се парсира '{name}': {greshka}") from greshka

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(load_pdf(sys.argv[1])[:2000])
