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

class Stats:    #broi uspesi i neuspesi za finalen izvestaj i izlezen kod 
    def __init__(self) -> None: #konstruktor
        self.chunks = 0 #broj na vkupno zapisani parcinja
        self.sources_ok = 0 #kolku izvori uspeale
        self.failures: list[tuple[str, str]] = []  #lista od neuspeh

    def ok(self, broj_parchinja: int) -> None:  #se povikuva pri uspeh
        self.chunks += broj_parchinja   #se dodavaat parcinjata na vkupniot broj
        self.sources_ok += 1    #zgolemuvanje na brojot ispesni izvori

    def fail(self, izvor: str, pricina: str) -> None:   # se povikuva pri neuspeh
        self.failures.append((izvor, pricina))  #go zapisuva neuspehot 
        logger.error("Неуспех за %s: %s", izvor, pricina) #Prikazuvanje na greska 

def _stable_id(izvor: str, indeks: int, tekst: str) -> str: #kreiranje na id za sekoe parce. za da nemame poveke parcinja so isti id
    otpecatok = hashlib.sha256(f"{izvor}:{indeks}:{tekst}".encode("utf-8")).hexdigest() #hesh od izvorot indeksot i teksto. dava 64 znacen fingerprint, ist za isti vlezovi
    return str(uuid.UUID(otpecatok[:32]))   #praveme 32 hex znaci vo UUID = Qdrant bara UUID format

def _now() -> str: #tekovno vreme kako tekst 
    return datetime.now(timezone.utc).isoformat()   #UTC vreme vo iso format, utc da e kozistentno bez razlika na vremenska zona

def _load_yaml(path: Path) -> dict: #bezbedno vcituvanje na yaml
    podatoci = yaml.safe_load(path.read_text(encoding="utf-8")) #citanje i prasiranje 
    if podatoci is None: #ako fajlot e prazen 
        return {}   #prazen recnik
    if not isinstance(podatoci, dict):  #ako vrvot ne e mapping/recnik
        raise ValueError(f"{path.name}: очекуван mapping на највисоко ниво") #frlanje na greska 
    return podatoci 

def _load_pdf_manifest() -> dict[str, dict]:  #citanje na data/pdfs.yaml 
    if not PDF_MANIFEST.exists():   #dokolku ne postoi 
        return {}   #se vraka prazno 
    try:
        konfig = _load_yaml(PDF_MANIFEST)   #vcitaj go 
    except (yaml.YAMLError, ValueError) as e: #dokolku ne validen 
        logger.warning("Невалиден %s — игнориран: %s", PDF_MANIFEST.name, e)
        return {} #vraka prazen recnik
    manifest_pdf = {} #gradime recnik
    for element in konfig.get("pdfs", []):  #mineme niz stavkite pod pdfs
        if isinstance(element, dict) and element.get("file"): #dokolku e validno zapis so pole file
            manifest_pdf[element["file"]] = element #zapis so imeto na fajlot 
        else:
            logger.warning("Прескокнат невалиден запис во pdfs.yaml: %r", element)
    return manifest_pdf 

def _push(parchinja: list[Chunk], izvor: str, dry_run: bool) -> int:    #zapisuvanje na parcinjata vo bazata i za pdf i za web
    if not parchinja:   #ako nema parcinja
        return 0    #ne zapisuvame nisto
    if dry_run: 
        logger.info("[dry-run] %s: %d парчиња (не се запишани)", izvor, len(parchinja))
        return len(parchinja)
    vreme = _now()  #vremenskata oznaka za site parcinja
    tekstovi, metadatoci, identifikatori = [], [], []
    for indeks, parche in enumerate(parchinja): #minenje niz sekoe parce so indeks
        parche.metadata["ingested_at"] = vreme  # zapisuvanje koga e vneseno
        tekstovi.append(parche.text)    #sobiranje na tekstot
        metadatoci.append(parche.metadata)  #sobiranje na metadata
        identifikatori.append(_stable_id(izvor, indeks, parche.text))   #generiranje na id
    upsert_chunks(tekstovi, metadatoci, identifikatori) #site zapisi se vnesuvat vo bazata
    return len(parchinja)   #vraka broj na podatoci, parcinja zapisani vo bazata

def _replace_source(parchinja: list[Chunk], izvor: str, dry_run: bool) -> int:
    if not parchinja:   #dokolku nema novi parcinja 
        logger.warning("%s: 0 парчиња — старите податоци остануваат недопрени", izvor)
        return 0
    if not dry_run: #dokolku ne e test 
        delete_by_source(izvor) #brisenje na stari parcinja za ovoj izvor 
    return _push(parchinja, izvor, dry_run) #zapis na novite

def ingest_pdfs(statistika: Stats, dry_run: bool) -> None:  #obrabotka na site lokaln pdf fajlovi
    if not PDF_DIR.exists():    #ako patekate ne postoi
        logger.warning("Нема папка %s", PDF_DIR)
        return 
    manifest_pdf = _load_pdf_manifest() #vcituvanje na naslov link manifest
    pdf_fajlovi = sorted(PDF_DIR.rglob("*.pdf")) #rglob = rekurzivno niz site podpapki 
    if not pdf_fajlovi: 
        logger.warning("Нема PDF фајлови во %s", PDF_DIR)
    for pdf in pdf_fajlovi: #minenje niz site pdf 
        izvor = str(pdf.relative_to(PDF_DIR))   #zemanje na relativnata pateka kako izvor 
        try:    #izoliranje na greska po fajlovi
            meta_zapis = manifest_pdf.get(izvor, {}) or manifest_pdf.get(pdf.name, {}) #baraj naslov/link po pateka, pa po ime
            tekst = load_pdf(pdf)   #vadenje na tekstot od pdf
            parchinja = chunk_document( #tekstot se sece na parcinja
                tekst, source=izvor, doc_type="pdf",
                title=meta_zapis.get("title") or pdf.stem, url=meta_zapis.get("url"),
            )
            # strukturata na papkite -> metadata (za filtriranje i podobar prikaz)
            pateka_delovi = pdf.relative_to(PDF_DIR).parts[:-1] #delovite od patekata bez imeto na fajlit, [:-1] se osven poslednoto
            for parche in parchinja:      #dodavanje na struktura metadata na sekoe parce
                if len(pateka_delovi) >= 1: #dokolku imame barem edno nivo papka
                    parche.metadata["ciklus"] = pateka_delovi[0]    #prva papka = ciklus (prv vtor tret)
                if len(pateka_delovi) >= 3: # ako ima dovolno nivoa
                    parche.metadata["fakultet"] = pateka_delovi[2]
                if len(pateka_delovi) >= 4:
                    parche.metadata["nasoka"] = pateka_delovi[3]    #papka za nasoka na sekoj faks
            broj_parchinja = _push(parchinja, izvor, dry_run)   #zapis na parcinjata
            statistika.ok(broj_parchinja)   #se oznacuvaat kako uspeh
            logger.info("[+] %s: %d парчиња", izvor, broj_parchinja)
        except Exception as greshka:  #dokolku se jave greksa 
            statistika.fail(izvor, str(greshka))    #se oznacuva neuspeh za fajlot 

def _ingest_crawled_pdf(adresa: str, podatoci: bytes, statistika: Stats, dry_run: bool) -> None:    #pdf najden pri crawl vo memorijata 
    try:
        tekst = load_pdf_bytes(podatoci, name=adresa)   #vadenje na tekstot od bajti bez zapos na diskot
        naslov = Path(adresa.split("?")[0]).name or adresa  #naslov = imet na fajl od url 
        parchinja = chunk_document(tekst, source=adresa, doc_type="pdf", title=naslov, url=adresa)  #isecenite parcinja na tekst 
        broj_parchinja = _replace_source(parchinja, adresa, dry_run)
        statistika.ok(broj_parchinja)
        logger.info("[+] (pdf) %s: %d парчиња", adresa, broj_parchinja)
    except PdfError as greshka: #dokolku pdf imam nekoj prb
        statistika.fail(adresa, str(greshka))   #se oznacuva kako neuspeh


def _ingest_page(adresa: str, naslov: str, tekst: str, statistika: Stats, dry_run: bool) -> None:   #za html stranica
    parchinja = chunk_document(tekst, source=adresa, doc_type="web", title=naslov, url=adresa)  #isecoci od web sto se dobivat
    broj_parchinja = _replace_source(parchinja, adresa, dry_run)   
    statistika.ok(broj_parchinja)
    logger.info("[+] %s: %d парчиња", naslov, broj_parchinja)


def ingest_web(statistika: Stats, dry_run: bool) -> None:  #obrabotka na web izvori od sources.yaml
    if not SOURCES_YAML.exists():   #dokolku nema sources
        logger.warning("Нема %s", SOURCES_YAML)
        return  #ne vraka nisto
    try:
        konfig = _load_yaml(SOURCES_YAML)   #vo sportivno imame vcituvanje na yaml
    except (yaml.YAMLError, ValueError) as greshka: #dokolku ne e validen 
        statistika.fail(SOURCES_YAML.name, f"невалиден YAML: {greshka}")
        return

    for zapis in konfig.get("web_sources", []):  #minenje niz sekoj izvor od web_sources: 
        if not isinstance(zapis, dict) or not zapis.get("url"): #dokolku zapisot e nevaliden ili nema url 
            statistika.fail("sources.yaml", f"невалиден запис (нема adresa): {zapis!r}")    #frlanje na greska
            continue
        adresa = str(zapis["url"]).strip()  #se zema adresata 
        naslov = zapis.get("title") or adresa   #se koriste naslovot od zapisot ili samata adresa
        try:
            if adresa.split("?")[0].lower().endswith(".pdf"):   #ako adresata e direkten pdf link
                podatoci = download_pdf(adresa) #istiot se prezema 
                tekst = load_pdf_bytes(podatoci, name=adresa)   #tekstot se vlece od linkot 
                parchinja = chunk_document(tekst, source=adresa, doc_type="pdf", title=naslov, url=adresa)  #izleceniot tekst se deli na parcinja
                broj_parchinja = _replace_source(parchinja, adresa, dry_run)   
                statistika.ok(broj_parchinja)
                logger.info("[+] (pdf) %s: %d парчиња", naslov, broj_parchinja)
            elif zapis.get("crawl"):    #doolku zapisot bara crawl 
                rezultat = crawl(   # se vrsi crawl
                    adresa,
                    max_depth=int(zapis.get("max_depth", DEFAULT_CRAWL_DEPTH)), #zemame dlabocina
                    max_pages=int(zapis.get("max_pages", DEFAULT_CRAWL_PAGES)), #max stranici
                    fetch_pdfs=bool(zapis.get("fetch_pdfs", True)), #dali e prezemen pdfot 
                )   
                for stranica in rezultat.pages: #minenje niz pronajdenite stranici
                    naslov_stranica = stranica.title if stranica.url != adresa else naslov  #koristeme naslov od stranicite samo ne se zima toj od pocetnata
                    _ingest_page(stranica.url, naslov_stranica, stranica.text, statistika, dry_run) #vnes na stranicata
                for pdf_adresa, podatoci in rezultat.pdfs.items():  #pominuvame niz prezemenite pdf ovi
                    _ingest_crawled_pdf(pdf_adresa, podatoci, statistika, dry_run) #vnesi go sekoj pdf
                for losha_adresa, pricina in rezultat.errors.items():   #minenje niz greskite od crawl
                    logger.warning("Прескокнато при crawl: %s (%s)", losha_adresa, pricina)
            else:
                tekst = scrape_url(adresa)  # se vade tekstot od stranicata
                _ingest_page(adresa, naslov, tekst, statistika, dry_run)   #se vnesuva
        except Exception as greshka:  # fakanje na bilo koja greska 
            statistika.fail(adresa, str(greshka))   #oznacuvanje kako neuspeh

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter) #parser za argumenti
    ap.add_argument("--only", choices=["pdf", "web"])   #samo ende izvor 
    ap.add_argument("--dry-run", action="store_true", help="scrape + parche без пишување во Qdrant")  #pravi test bez zapis
    ap.add_argument("-v", "--verbose", action="store_true") 
    argumenti = ap.parse_args() #citanje na argumenti od komandata
    logging.basicConfig(
        level=logging.DEBUG if argumenti.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    statistika = Stats()    #sozdavanje na brojac
    if not argumenti.dry_run:   #ako ne e test
        ensure_collection()    #proverka dali qdrant kolekcijata postoe
    if argumenti.only in (None, "pdf"): #dokolku ne e zadadeno onlu ili e pdf 
        ingest_pdfs(statistika, argumenti.dry_run)  # se obrabotuvaat lokalnite pdf
    if argumenti.only in (None, "web"): #ako ne e zadadeno only ili web
        ingest_web(statistika, argumenti.dry_run)   #obrabotka na web izvori
    logger.info("Вкупно %d парчиња од %d извори во '%s' (hybrid=%s)%s", statistika.chunks, statistika.sources_ok, settings.qdrant_collection,settings.use_hybrid, " [dry-run]" if argumenti.dry_run else "")    #finalen izvestaj
    if statistika.failures: #dokolku se jave neuspeh
        logger.error("Неуспешни извори (%d):", len(statistika.failures))
        for izvor, pricina in statistika.failures:  #mineme niz sekoj
            logger.error("  - %s: %s", izvor, pricina)
        return 1    #dava izlez 1
    return 0 #izlez 0 koga nema da se javat greski

if __name__ == "__main__":
    sys.exit(main())
