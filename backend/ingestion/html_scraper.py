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
REQUEST_TIMEOUT = (10, 20)          
MAX_HTML_BYTES = 5 * 1024 * 1024  
MAX_PDF_BYTES = 30 * 1024 * 1024    
MAX_PAGES_PER_CRAWL = 30            
CRAWL_DELAY_SECONDS = 0.5          
RETRY_TOTAL = 3
RETRY_BACKOFF = 0.5
ALLOWED_SCHEMES = frozenset({"http", "https"})
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

# Тагови што се шум за retrieval
_STRIP_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "iframe", "form", "svg", "aside", "button"]


@dataclass
class Page:
    url: str
    title: str
    text: str

@dataclass
class CrawlResult:
    pages: list[Page] = field(default_factory=list)
    pdfs: dict[str, bytes] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class ScrapeError(Exception):
    """Грешка при преземање/парсирање на URL (безбедна за прикажување)."""

def _validate_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsirano = urlparse(url)
    if parsirano.scheme not in ALLOWED_SCHEMES:
        raise ScrapeError(f"Недозволена шема '{parsirano.scheme}' (само http/https)")
    if not parsirano.hostname:
        raise ScrapeError("URL без hostname")
    if parsirano.username or parsirano.password:
        raise ScrapeError("URL со вградени креденцијали не е дозволен")
    try:
        adres_info = socket.getaddrinfo(parsirano.hostname, parsirano.port or 0,
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as greshka:
        raise ScrapeError(
            f"Не може да се резолвира '{parsirano.hostname}': {greshka}") from greshka
    for info in adres_info:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ScrapeError(
                f"'{parsirano.hostname}' резолвира на недозволена адреса {ip} (SSRF заштита)"
            )
    return url


def _same_domain(url: str, osnoven_domen: str) -> bool:
    domakin = (urlparse(url).hostname or "").lower()
    osnova = osnoven_domen.lower()
    return domakin == osnova or domakin.endswith("." + osnova)

def _make_session() -> requests.Session:
    sesija = requests.Session()
    sesija.headers.update({"User-Agent": USER_AGENT,
                            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5"})
    povtor = Retry(total=RETRY_TOTAL, backoff_factor=RETRY_BACKOFF,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET", "HEAD"}))
    adapter_http = HTTPAdapter(max_retries=povtor)
    sesija.mount("http://", adapter_http)
    sesija.mount("https://", adapter_http)
    sesija.max_redirects = 5
    return sesija


def _fetch(sesija: requests.Session, url: str, max_bytes: int) -> requests.Response:
    odgovor = sesija.get(url, timeout=REQUEST_TIMEOUT, stream=True)
    odgovor.raise_for_status()
    if odgovor.url != url:                       # редирект — провери ја крајната адреса
        _validate_url(odgovor.url)

    deklarirano = odgovor.headers.get("Content-Length")
    if deklarirano and deklarirano.isdigit() and int(deklarirano) > max_bytes:
        odgovor.close()
        raise ScrapeError(f"Одговорот е преголем ({deklarirano} B > {max_bytes} B)")
    telo = bytearray()
    for delce in odgovor.iter_content(chunk_size=65536):
        telo.extend(delce)
        if len(telo) > max_bytes:
            odgovor.close()
            raise ScrapeError(f"Одговорот надмина {max_bytes} B — прекинато")
    odgovor._content = bytes(telo)               
    return odgovor

def _robots_allowed(sesija: requests.Session, url: str) -> bool:
    """Почитувај robots.txt (best-effort; при грешка дозволи)."""
    parsirano = urlparse(url)
    robots_adresa = f"{parsirano.scheme}://{parsirano.netloc}/robots.txt"
    robots_parser = urllib.robotparser.RobotFileParser()
    try:
        odgovor = sesija.get(robots_adresa, timeout=REQUEST_TIMEOUT)
        if odgovor.status_code >= 400:
            return True
        robots_parser.parse(odgovor.text.splitlines())
        return robots_parser.can_fetch(USER_AGENT, url)
    except requests.RequestException:
        return True

def _table_to_markdown(tabela) -> str:
    redovi = []
    for red_tabela in tabela.find_all("tr"):
        kelii = [kelija.get_text(" ", strip=True).replace("|", "/")
                 for kelija in red_tabela.find_all(["th", "td"])]
        if any(kelii):
            redovi.append("| " + " | ".join(kelii) + " |")
    if not redovi:
        return ""
    if len(redovi) >= 2:                        # header separator за валиден Markdown
        br_koloni = redovi[0].count("|") - 1
        redovi.insert(1, "|" + "---|" * max(br_koloni, 1))
    return "\n".join(redovi)

def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    for tabela in soup.find_all("table"):
        tabela_md = _table_to_markdown(tabela)
        tabela.replace_with(soup.new_string("\n" + tabela_md + "\n") if tabela_md else "")
    glavno = soup.find("main") or soup.find("article") or soup.body
    text = glavno.get_text(separator="\n") if glavno else soup.get_text("\n")
    linii = [linija.strip() for linija in text.splitlines() if linija.strip()]
    return "\n".join(linii)

def _parse_html(odgovor: requests.Response, url: str) -> tuple[Page, list[str], list[str]]:
    odgovor.encoding = odgovor.apparent_encoding or "utf-8"   # важно за кирилица
    soup = BeautifulSoup(odgovor.text, "html.parser")
    naslov_tag = soup.find("title")
    title = naslov_tag.get_text(strip=True) if naslov_tag else url
    html_linkovi, pdf_linkovi = [], []
    for kotva in soup.find_all("a", href=True):
        href = urljoin(url, kotva["href"].strip())
        href, _ = urldefrag(href)
        if urlparse(href).scheme not in ALLOWED_SCHEMES:
            continue
        if urlparse(href).path.lower().endswith(".pdf"):
            pdf_linkovi.append(href)
        else:
            html_linkovi.append(href)
    return Page(url=url, title=title, text=_extract_text(soup)), html_linkovi, pdf_linkovi

def _is_pdf_response(odgovor: requests.Response, url: str) -> bool:
    tip_sodrzina = (odgovor.headers.get("Content-Type") or "").lower()
    return "application/pdf" in tip_sodrzina or urlparse(url).path.lower().endswith(".pdf")

def scrape_url(url: str, sesija: requests.Session | None = None) -> str:
    url = _validate_url(url)
    sesija = sesija or _make_session()
    odgovor = _fetch(sesija, url, MAX_HTML_BYTES)
    tip_sodrzina = (odgovor.headers.get("Content-Type") or "").lower()
    if tip_sodrzina and not any(html_tip in tip_sodrzina for html_tip in HTML_CONTENT_TYPES):
        raise ScrapeError(f"Неочекуван Content-Type '{tip_sodrzina}' за {url}")
    page, _, _ = _parse_html(odgovor, url)
    return page.text

def download_pdf(url: str, sesija: requests.Session | None = None) -> bytes:
    url = _validate_url(url)
    sesija = sesija or _make_session()
    odgovor = _fetch(sesija, url, MAX_PDF_BYTES)
    if not _is_pdf_response(odgovor, url):
        raise ScrapeError(f"{url} не врати PDF содржина")
    return odgovor.content

def crawl(seed_url: str, max_depth: int = 1,
          max_pages: int = MAX_PAGES_PER_CRAWL,
          fetch_pdfs: bool = True,
          respect_robots: bool = True) -> CrawlResult:
    seed_url = _validate_url(seed_url)
    osnoven_domen = urlparse(seed_url).hostname or ""
    if osnoven_domen.startswith("www."):
        osnoven_domen = osnoven_domen[4:]
    sesija = _make_session()
    rezultat = CrawlResult()
    poseteni: set[str] = set()
    videni_pdf: set[str] = set()
    redica: list[tuple[str, int]] = [(seed_url, 0)]
    while redica and len(poseteni) < max_pages: # od tuka prodolzi posle
        url, dlabocina = redica.pop(0)
        if url in poseteni:
            continue
        poseteni.add(url)
        try:
            _validate_url(url)
            if respect_robots and not _robots_allowed(sesija, url):
                rezultat.errors[url] = "блокирано од robots.txt"
                continue
            odgovor = _fetch(sesija, url, MAX_PDF_BYTES if fetch_pdfs else MAX_HTML_BYTES)
            if _is_pdf_response(odgovor, url):
                if fetch_pdfs and len(odgovor.content) <= MAX_PDF_BYTES:
                    rezultat.pdfs[url] = odgovor.content
                continue
            tip_sodrzina = (odgovor.headers.get("Content-Type") or "").lower()
            if tip_sodrzina and not any(html_tip in tip_sodrzina for html_tip in HTML_CONTENT_TYPES):
                continue    # слики, docx итн. — прескокни тивко
            if len(odgovor.content) > MAX_HTML_BYTES:
                rezultat.errors[url] = "HTML преголем"
                continue
            page, html_linkovi, pdf_linkovi = _parse_html(odgovor, url)
            if page.text:
                rezultat.pages.append(page)
            if fetch_pdfs:
                for pdf_vrska in pdf_linkovi:
                    if pdf_vrska in videni_pdf or not _same_domain(pdf_vrska, osnoven_domen):
                        continue
                    videni_pdf.add(pdf_vrska)
                    try:
                        rezultat.pdfs[pdf_vrska] = download_pdf(pdf_vrska, sesija)
                        time.sleep(CRAWL_DELAY_SECONDS)
                    except (ScrapeError, requests.RequestException) as greshka:
                        rezultat.errors[pdf_vrska] = str(greshka)
            if dlabocina < max_depth:
                for vrska in html_linkovi:
                    if vrska not in poseteni and _same_domain(vrska, osnoven_domen):
                        redica.append((vrska, dlabocina + 1))
        except (ScrapeError, requests.RequestException) as greshka:
            rezultat.errors[url] = str(greshka)
            logger.warning("Прескокнат %s: %s", url, greshka)
        time.sleep(CRAWL_DELAY_SECONDS)
    logger.info("Crawl %s: %d страници, %d PDF-ови, %d грешки",
                seed_url, len(rezultat.pages), len(rezultat.pdfs), len(rezultat.errors))
    return rezultat

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(scrape_url(sys.argv[1])[:2000])
