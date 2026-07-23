from __future__ import annotations
import ipaddress
import logging
import socket
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urldefrag
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

USER_AGENT = "AskUGD-bot/1.0 (+https://ugd.edu.mk)" 
REQUEST_TIMEOUT = (10, 20)   #timeout kade imame 10s za povrazuvanje i 20s za citanje      
MAX_HTML_BYTES = 5 * 1024 * 1024  #max 5MB po html stranica 
MAX_PDF_BYTES = 30 * 1024 * 1024  #max 30MB po pdf
MAX_PAGES_PER_CRAWL = 30    #masimalno 30 stranici po crawl          
CRAWL_DELAY_SECONDS = 0.5   # pauza od 0,5s megju sekoe baranje so toa ne se optovaruva serverot       
RETRY_TOTAL = 3 #max 3 obidi pri pojava na mrezna greska 
RETRY_BACKOFF = 0.5 #mnozitel za sekanje megju obidite 
ALLOWED_SCHEMES = frozenset({"http", "https"})  #dozvoleni se samo http/https 
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml") #vrednosti sto se za html

_STRIP_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "iframe", "form", "svg", "aside", "button"]    #html tagovi sto se sum 

@dataclass
class Page: #rezultat od scrape na edna stranica
    url: str    #adresata
    title: str  #naslovot, se zima od <title>
    text: str   #iseceniot tekst 

@dataclass
class CrawlResult:  #rezultatot od celiot crawl 
    pages: list[Page] = field(default_factory=list) #lista pages objekti, sekoj CrawlResult dobiva svoja lista
    pdfs: dict[str, bytes] = field(default_factory=dict)    #bajti na prezemeniot pdf 
    errors: dict[str, str] = field(default_factory=dict)    # url recnik za greska

class ScrapeError(Exception):   #greska za problemi pri parsiranje 
    """Грешка при преземање/парсирање на URL (безбедна за прикажување)."""

def _validate_url(url: str) -> str: #proverka dali url e bezbedno za prezemanje, se povikuva pred sekoj fetch
    url, _ = urldefrag(url) # go trga delot po #, _ ne e potrebna
    parsirano = urlparse(url) #razlozuvanje na urlto, hostname, porta
    if parsirano.scheme not in ALLOWED_SCHEMES: #dozvoli samo da se obrabotuvaat baranja od http i https
        raise ScrapeError(f"Недозволена шема '{parsirano.scheme}' (само http/https)")
    if not parsirano.hostname:  # dokolku url nema hostname
        raise ScrapeError("URL без hostname")
    if parsirano.username or parsirano.password:   #se trgaat url so vgradeni kredencijali
        raise ScrapeError("URL со вградени креденцијали не е дозволен")
    try:
        adres_info = socket.getaddrinfo(parsirano.hostname, parsirano.port or 0, proto=socket.IPPROTO_TCP)  # rezolviranje na hostname vo ip adresi, so porta i 0 ako nema porta
    except socket.gaierror as greshka:  #dokolku dns ne uspee
        raise ScrapeError(
            f"Не може да се резолвира '{parsirano.hostname}': {greshka}") from greshka  # se dava greska 
    for info in adres_info: # proverka na site dobienie ip adresi
        ip = ipaddress.ip_address(info[4][0])   # info[4][0] e ip adresata, se pretvara vo ip_adress objekt
        if (ip.is_private or ip.is_loopback or ip.is_link_local # se odbivaat sekakvi lokalno ili privatni ip adresi
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ScrapeError(
                f"'{parsirano.hostname}' резолвира на недозволена адреса {ip} (SSRF заштита)"
            )
    return url  #dokolku site cekori pominat se vraka normalizirano url

def _same_domain(url: str, osnoven_domen: str) -> bool: #proverka dali url e na istiot domen 
    domakin = (urlparse(url).hostname or "").lower()    # hostname na url to
    osnova = osnoven_domen.lower() 
    return domakin == osnova or domakin.endswith("." + osnova) # tocno sovpaganje ili poddomen 

def _make_session() -> requests.Session:    #sozdavanje na sesija 
    sesija = requests.Session() #sesija dali ima konekcii megu baranjata
    sesija.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5"})  #postavuvanje na nazivot na ai agentot i sto e prifanato
    povtor = Retry(total=RETRY_TOTAL, backoff_factor=RETRY_BACKOFF,
                  status_forcelist=(429, 500, 502, 503, 504),   # samo se davaat ovie statusni kodovi
                  allowed_methods=frozenset({"GET", "HEAD"}))   #samo get/head metodi sto moze da se koristat
    adapter_http = HTTPAdapter(max_retries=povtor)   #afapter sto ja preimenuva strategijata
    sesija.mount("http://", adapter_http)      #zakacuvanje na http
    sesija.mount("https://", adapter_http)     # https
    sesija.max_redirects = 5    # definiranje na max 5 predirekti
    return sesija


def _fetch(sesija: requests.Session, url: str, max_bytes: int) -> requests.Response:    #se prezema url so streaming i limit na golemina
    odgovor = sesija.get(url, timeout=REQUEST_TIMEOUT, stream=True) # stream = true cita parce po parce
    odgovor.raise_for_status()  #dokolku se java status so greska (4xx 5xx) frla greska 
    if odgovor.url != url:      # ako ima redirekt se pravi validacija na krajnata adresa          
        _validate_url(odgovor.url)
    deklarirano = odgovor.headers.get("Content-Length") #citanje na deklariraniot content lenght 
    if deklarirano and deklarirano.isdigit() and int(deklarirano) > max_bytes: #dokolki brojot e naj limitot imame odbivanje vednas 
        odgovor.close()
        raise ScrapeError(f"Одговорот е преголем ({deklarirano} B > {max_bytes} B)")
    telo = bytearray()  #prazen bafer vo koj smestuvame sodrzinata
    for delce in odgovor.iter_content(chunk_size=65536):    #se cita parce po parce 
        telo.extend(delce)  
        if len(telo) > max_bytes:   # dokolku telot od html ja nadmine goleminata 
            odgovor.close() 
            raise ScrapeError(f"Одговорот надмина {max_bytes} B — прекинато")   #se definiran prekin 
    odgovor._content = bytes(telo)   #go postavuvame telto nazad vo odgovoror za da rabotat .text/.content.            
    return odgovor

def _robots_allowed(sesija: requests.Session, url: str) -> bool:    #proverka dali moze da se zeme stranicata
    parsirano = urlparse(url)   
    robots_adresa = f"{parsirano.scheme}://{parsirano.netloc}/robots.txt"   #sostavuvanje na adresata na robots.txt
    robots_parser = urllib.robotparser.RobotFileParser()    #parsiranje za pravilata
    try:
        odgovor = sesija.get(robots_adresa, timeout=REQUEST_TIMEOUT)    #prezemanje na pobost.txt
        if odgovor.status_code >= 400:  #dokolku ne postoi dozvoli 
            return True
        robots_parser.parse(odgovor.text.splitlines())  #parsiranje na pavilata ode linija po linija
        return robots_parser.can_fetch(USER_AGENT, url) # ako robots.txt e nedostapna ili greska dozvoleno e nema rusenje na crawl
    except requests.RequestException:   
        return True

def _table_to_markdown(tabela) -> str:  #pretvaranje na html <table> vo markdown tabela
    redovi = []
    for red_tabela in tabela.find_all("tr"):    #mineme niz sekoj red vo tabelata
        kelii = [kelija.get_text(" ", strip=True).replace("|", "/") 
                 for kelija in red_tabela.find_all(["th", "td"])]
        if any(kelii): #dodavanje na red samo ako ima barem edna nepovrzana kelija
            redovi.append("| " + " | ".join(kelii) + " |")  
    if not redovi:
        return ""   #dokolku ne se najdeni redovi se vraka prazno
    if len(redovi) >= 2:                        # validna markdown tabela ke treba da ima separator po zaglavieto
        br_koloni = redovi[0].count("|") - 1    # beoj na koloni
        redovi.insert(1, "|" + "---|" * max(br_koloni, 1)) #vmetnuvanje na separator linijata na pozcija 1 
    return "\n".join(redovi)

def _extract_text(soup: BeautifulSoup) -> str:  #vadenje na cist tekst od html
    for tag in soup(_STRIP_TAGS):   #otstranuvanje na sum tagovite, navigacija, skripti....
        tag.decompose()  # decompose prave celosno brisenje od dokumentot
    for tabela in soup.find_all("table"):   #zamena na sekoja tabela so nejzina markdown verzija
        tabela_md = _table_to_markdown(tabela)  
        tabela.replace_with(soup.new_string("\n" + tabela_md + "\n") if tabela_md else "") #dokolku tabelata ima tekst se zamenuva inake se ostanuva prazno
    glavno = soup.find("main") or soup.find("article") or soup.body #zemanje na glavnite delovi <main> ili <article> moze da se zema i celiot body
    text = glavno.get_text(separator="\n") if glavno else soup.get_text("\n")   #vadenje na tekstot so nova linija kako separator
    linii = [linija.strip() for linija in text.splitlines() if linija.strip()]  #secenje na sekoja linija i isfral nje na praznini
    return "\n".join(linii)

def _parse_html(odgovor: requests.Response, url: str) -> tuple[Page, list[str], list[str]]: #parsiranje na html = pages = html linkovi i pdf linkovi
    odgovor.encoding = odgovor.apparent_encoding or "utf-8"   #postavuvanje na utf da moze da se zeme kirilica
    soup = BeautifulSoup(odgovor.text, "html.parser")   #parsiranje na html
    naslov_tag = soup.find("title") #pronaoganje na <title> kako tag
    title = naslov_tag.get_text(strip=True) if naslov_tag else url  #zemi go naslovot, ako nema koristeme go urlto 
    html_linkovi, pdf_linkovi = [], []  #formiranje na dve listi edna za html i druga za pfd linkovi
    for kotva in soup.find_all("a", href=True): # pominuvanje nis sekoj <a href = > tag
        href = urljoin(url, kotva["href"].strip())  #pretvaranje na relativen vo apsoluten link
        href, _ = urldefrag(href)     #otstranuvanje na fragmentot #
        if urlparse(href).scheme not in ALLOWED_SCHEMES:    #preskoknuvanje na linkovi koj ne se http i https
            continue
        if urlparse(href).path.lower().endswith(".pdf"):    #dokolku se naide na pateka koja ima zavrasetok .pdf se zima pdf linkot
            pdf_linkovi.append(href)
        else:
            html_linkovi.append(href)   #inaku zemame go html linkot 
    return Page(url=url, title=title, text=_extract_text(soup)), html_linkovi, pdf_linkovi  #vraka page i dvete listi

def _is_pdf_response(odgovor: requests.Response, url: str) -> bool: #proveruva dali odgovorot e pdf, 
    tip_sodrzina = (odgovor.headers.get("Content-Type") or "").lower()
    return "application/pdf" in tip_sodrzina or urlparse(url).path.lower().endswith(".pdf")

def scrape_url(url: str, sesija: requests.Session | None = None) -> str: #javna funkcija vraka tekst od edna stranica se povikuva od run_ingestion 
    url = _validate_url(url)    #validiranje na url 
    sesija = sesija or _make_session()  #koristenje na tekovna sesija ili kreiranje na nova dokolku nema aktivna 
    odgovor = _fetch(sesija, url, MAX_HTML_BYTES) #prezemanje na odgovorot
    tip_sodrzina = (odgovor.headers.get("Content-Type") or "").lower()  #proverka na contetn type
    if tip_sodrzina and not any(html_tip in tip_sodrzina for html_tip in HTML_CONTENT_TYPES):   #dokolku ne e html frlanje na greska 
        raise ScrapeError(f"Неочекуван Content-Type '{tip_sodrzina}' за {url}") 
    page, _, _ = _parse_html(odgovor, url)  #parsiranje i vrakanje na tekstot
    return page.text

def download_pdf(url: str, sesija: requests.Session | None = None) -> bytes:    #prezemanje na odf i vrakanje an bajtite, se vika od run_ingestion i crawl
    url = _validate_url(url)
    sesija = sesija or _make_session()
    odgovor = _fetch(sesija, url, MAX_PDF_BYTES)
    if not _is_pdf_response(odgovor, url):  #proverka dali e pdf
        raise ScrapeError(f"{url} не врати PDF содржина")
    return odgovor.content

def crawl(seed_url: str, max_depth: int = 1,    #BFS crawl od poceten URL, samo na istiot domen
          max_pages: int = MAX_PAGES_PER_CRAWL, 
          fetch_pdfs: bool = True,
          respect_robots: bool = True) -> CrawlResult:
    seed_url = _validate_url(seed_url)  #validiranje na pocetniot url
    osnoven_domen = urlparse(seed_url).hostname or ""   #se zema osnovniot domen 
    if osnoven_domen.startswith("www."):    # go trga www.ugd.edu.mk = ugd.edu.mk
        osnoven_domen = osnoven_domen[4:]   #za da se dade pristap i na poddomenite
    sesija = _make_session() #definiranje na edna sesija za celiot crawl
    rezultat = CrawlResult()    #prazen rezultat, vo koj ke se smestuvat infromacii dobieni 
    poseteni: set[str] = set()  #set na poseteni url, da ne mora da se povtoruvaat sekoj pat 
    videni_pdf: set[str] = set()    #prezemani pdf linkovi , sodrzini
    redica: list[tuple[str, int]] = [(seed_url, 0)] #redica za url
    while redica and len(poseteni) < max_pages: # dodeka ima sto da se obrabotuva i ne go dostignuva limitot 
        url, dlabocina = redica.pop(0)  #zemi go prviot od redicata
        if url in poseteni: #dokolku e poseten se preskoknuva da ne se duplikat pravat
            continue
        poseteni.add(url)   #se oznacuva kako poseten
        try:
            _validate_url(url)  #povratna validacija 
            if respect_robots and not _robots_allowed(sesija, url): #dokolku robots.txt ne dozvoluva 
                rezultat.errors[url] = "блокирано од robots.txt"    # se zapisuva greska i se dava prekin
                continue
            odgovor = _fetch(sesija, url, MAX_PDF_BYTES if fetch_pdfs else MAX_HTML_BYTES)  #prezemanje so pdf limit ako sobira pdf 
            if _is_pdf_response(odgovor, url): #dokolku e pdf
                if fetch_pdfs and len(odgovor.content) <= MAX_PDF_BYTES:    # dokolku e pod limitot
                    rezultat.pdfs[url] = odgovor.content    #zacuvuvanje na bajtite
                continue
            tip_sodrzina = (odgovor.headers.get("Content-Type") or "").lower()
            if tip_sodrzina and not any(html_tip in tip_sodrzina for html_tip in HTML_CONTENT_TYPES): #dokolku ne e html (slikim docx )
                continue  #se preskoknuva ne se zima vo predvid 
            if len(odgovor.content) > MAX_HTML_BYTES:  #dokolku html e predolg 
                rezultat.errors[url] = "HTML преголем"  # se dava greska i se preskoknuva
                continue
            page, html_linkovi, pdf_linkovi = _parse_html(odgovor, url) #parsiranje na stranicata
            if page.text:   #dokolku ima tekst 
                rezultat.pages.append(page) #zacuvuvanje na stranicata
            if fetch_pdfs:  #dokolku se javi pdf fajlovi, gi zemame od stanicata 
                for pdf_vrska in pdf_linkovi:
                    if pdf_vrska in videni_pdf or not _same_domain(pdf_vrska, osnoven_domen): #dokolku pdf e veke zeman ili e na nekoj drug doman se preskoknuva ne go prezemam
                        continue
                    videni_pdf.add(pdf_vrska)   #se oznacuva kako validen 
                    try:
                        rezultat.pdfs[pdf_vrska] = download_pdf(pdf_vrska, sesija) #prezemanje na pdf
                        time.sleep(CRAWL_DELAY_SECONDS) #se stava pauza
                    except (ScrapeError, requests.RequestException) as greshka:
                        rezultat.errors[pdf_vrska] = str(greshka)
            if dlabocina < max_depth:   #dokolku ja dostignam maksimalnata dlabocina 
                for vrska in html_linkovi: # se dodavat html linkovite za sledenje 
                    if vrska not in poseteni and _same_domain(vrska, osnoven_domen): #samo linkovi na istiot domen 
                        redica.append((vrska, dlabocina + 1)) #dodavanje na stranicata so zgolemena dlabocina
        except (ScrapeError, requests.RequestException) as greshka: #dokolku stranicata padne 
            rezultat.errors[url] = str(greshka) #se frla greska 
            logger.warning("Прескокнат %s: %s", url, greshka)
        time.sleep(CRAWL_DELAY_SECONDS) #se stava pauza megu sekok dve stranici
    logger.info("Crawl %s: %d страници, %d PDF-ови, %d грешки", seed_url, len(rezultat.pages), len(rezultat.pdfs), len(rezultat.errors))
    return rezultat

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(scrape_url(sys.argv[1])[:2000])
