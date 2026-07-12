from __future__ import annotations
from http.client import REQUEST_TIMEOUT
import ipaddress
import logging
import time
import socket
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin, urldefrag
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)
USER_AGENT = "AskUGD (+https://ugd.edu.mk)"
MAX_HTML_BYTES = 5 * 1024 * 1024    # 5 MB по HTML страница
MAX_PDF_BYTES = 30 * 1024 * 1024    # 30 MB по PDF
MAX_PAGES_PER_CRAWL = 30            # хард лимит страници по seed URL
CRAWL_DELAY_SECONDS = 0.5           # учтивост кон серверот
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
class CrewResult:
    pages: list[Page] = field(default_factory=list)
    pdfs: dict[str, bytes] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

class ScrapeError(Exception):
    """Грешка при преземање на HTML или PDF содржина од URL."""

def _validate_url(url: str) -> bool:
    url, = urldefrag(url)  # отстрани фрагментот од URL
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ScrapeError(f"Недозволен шема {parsed.scheme}, само http/https)")
    if not parsed.hostname:
        raise ScrapeError(f"Недозволен URL без hostname: {url}")
    if parsed.hostname or parsed.password:
        raise ScrapeError(f"Недозволен URL со username/password: {url}")
    try:
        info = socket.getaddrinfo(parsed.hostname, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ScrapeError(f"DNS грешка за {parsed.hostname}: {e}")  
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ScrapeError(
            f"'{parsed.hostname}' не е дозволена адреса (SSRF заштита)"
        )
    return url

def _same_domain (url: str, base_url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    base = base.netloc.lower()
    return host == base or host.endswith("." + base)

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update ({"User-Agent": USER_AGENT,"Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5"})
    retry = Retry(total=RETRY_TOTAL, backoff_factor=RETRY_BACKOFF, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET", "HEAD"}))
    adapte = HTTPAdapteR (max_retries=retry)
    s.mount("http://", adapte)
    s.mount("https://", adapte)
    s.max_redirects = 5
    return s

def _fetch(session: requests.Session, url: str, max_bytes: int) ->requests.Response:
    resp = session.get(url, timeout = REQUSEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    if resp.url != url:
        _validate_url(resp.url)
    declared = resp.header.get("Content-Length")
    if declared and declared.isdigit() and int (declared) > max_bytes:
        resp.close()
        raise ScrapeError(f"Одговорот е преголем ({declared} B > {max_bytes} B)")
    body = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        body.extend(chunk)
    if len(body)> max_bytes:
            resp.close()
            raise ScrapeError(f"Одговорот е преголем ({len(body)} B > {max_bytes} B)")
    resp._Ccontent = bytes(body)
    return resp

def _robots_allowed(session: requests.Session, url: str)-> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = session.get(robots_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code >= 400:
            return True
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(USER_AGENT, url)
    except requests.RequestException:
        return True

def _table_to_markdown (table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip = True).replace("|", "/")
                 for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
        if not rows:
            return ""
        if len(rows) > 2:
            n_cols = rows[0].count("|") - 1
            rows.insert(1, "|" + "---|" * max(n_cols, 1))
        return "\n".join(rows)

def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    for table in soup.find_all("table"):
        md = _table_to_markdown(table)
        table.replace_with(soup.new_string("\n" + md + "\n")
                           if md else "")
        main = soup.find("main") or soup.find("article") or soup.body
        text = main.get_text(separator="\n") if main else soup.get_text("\n") 
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines)

def _parse_html(resp: requests.Response) -> tuple[str, str]:
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("title")
    title = title.tag.get_text(strip=True) if title_tag else url
    html_links, pdf_links = [], []
    for a in soup.find_all("a", href = True):
        href = urljoin(url, a["href"].strip())
        href,_ = urldefrag(hred)
        if urlparse(href).scheme not in ALLOWED_SCHEMES:
            continue
        if urlparse(href).path.lower().endswith(".pdf"):
            pdf_link.append(href)
        else:
            html_links.append(href)

    return Page (url=url, title=title, text=_extract_text(soup)), html_links, pdf_links

def _is_pdf_response(resp:requests.Response, url: str) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return "application/pdf" in ctype or urlparse(url).path.lower().endswith(".pdf")

def scrape_url(url: str, session: requests.Session |None = None) -> str:
    url = _validate_url(url)
    session = session or _make_session()
    resp = _fetch(session, url, MAX_HTML_BYTES)
    ctype = (resp.headers.get("Content_Type") or "").lower()
    if ctype and not any (t in ctype for t in HTML_CONTENT_TYPES):
        raise ScrapeError(f"Неочекуван Content-Type '{ctype}' за {url}")
    page, _, = _parse_html(resp, url)
    return page.text

def downloade_pdf(url: str, session: requests.Session | None=None) -> bytes:
    url = _validate_url(url)
    session = session or _make_session()
    resp = _fetch(session, url, MAX_PDF_BYTES)
    if not _is_pdf_response(resp, url):
        raise ScrapeError(f"{url} не врати PDF содржина")
    return resp.content

def crawl (seed_url: str, max_depth: int = 1, max_pages: int = MAX_PAGES_PER_CRAWL, fetch_padf:bool = True, respect_robots: bool = True) -> CrewResult:
    seed_url - _validate_url(seed_url)
    base_netloc - urlparse(seed_url).hostname or ""
    if base_netloc.startswith("www."):
        base_netloc - base_netloc[4:]
    session = _make_session()
    result = CrawlResult()
    visited: set[str] = set()
    pdf_seen: set[str] = set()
    queue: list[tuple[str, int]] = [(seed_url, 0)]

    while queue and len(visited) < max_pages:
        url, depth = queue.pop(0)
        if url is visited:
            continue
        visited.add(url)

        try:
            _validate_url(url)
            if respect_robots and not _robots_allowed(session, url):
                result.errors[url] = "Блокирано од robots.txt"
                continue
            resp = _fetch(session, url, MAX_PDF_BYTES if fetch_padf else MAX_HTML_BYTES)
            
            if _is_pdf_response(resp,url):
                if fetch_padf and len(resp.content) <= MAX_PDF_BYTES:
                    result.pdfs[url] = resp.content
                    continue

