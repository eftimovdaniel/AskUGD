from __future__ import annotations
import logging
from app.config import settings
from app.core import rerank as reranker
from app.core import vectorstore
from app.core.translate import translate_query

logger = logging.getLogger(__name__)

class RetrievalUnavailable(Exception):  # greska od tip na toa deka the database?embeddings se nedostapni
    pass

def _query_variants(prashanje: str) -> list[str]: #se pravi poveke verzii na prasanjeto (orginalot i prevod), site dokumenti se na mkd, ako se postave prasanje od student na angliski se preveduva vednas
    varijanti = [prashanje] # pocnuvam so orginalnoto prasanje, postaveno od strana na studentot
    rezultat = translate_query(prashanje) #obid da se napravi prevod, vraka TranslationResult objekt
    prevod = rezultat.translated   # se vadi prevodot, dokolku go ima ili vraka None dokolku ne moze da se prevede
    if prevod and prevod.lower() != prashanje.lower():  # go dodavam samo ako ima prevod i e razlicen od orginalot, ako e na mkd ne mora da se preveduva na mkd 
        varijanti.append(prevod)   # se dodava prevedenata verzija
    return varijanti[: settings.max_retrieval_iterations]   # se ograniciva brojot na varijanti, se garantira deka nema da se preveduva beskonecno mnogu

def retrieve(prashanje: str) -> list[dict]: # dava najrelevantno prace za prasanjeto
    videni: dict[str, dict] = {}   #recnik: id na parceto se zema parceto, za da se otstrant duplikati 
    varijanti = _query_variants(prashanje)  #se zemaat serziite na prasanjeto
    neuspesi = 0   #brojot na neuspesni prebaruvanja

    for varijanta_br, varijanta in enumerate(varijanti, 1): # pominuva nis sekoja verzija 
        try:   #prebaruvanjeto moze da padne ako Qdrant e nedostapen ili ne moze da se aktivira
            pogodoci = vectorstore.search(varijanta, limit=settings.candidate_k) #hybrid search vraka kandidati za ovaa varijanta 
        except Exception as greshka:  # dokolku padne 
            neuspesi += 1   # zgolemuvanje na brojacot na neuspesi
            logger.error("Search за варијанта %d падна: %s", varijanta_br, greshka) #logovi
            continue # se prodolzuva so slednata varijanta
        for pogodok in pogodoci:    # za sekoj pronajden kadidat
            prethoden = videni.get(pogodok["id"])   # se proveruva dali go imame parceto po id
            if prethoden is None or pogodok["score"] > prethoden["score"]:  #dokolku e nov ili ima povisok score od prethodno
                videni[pogodok["id"]] = pogodok # zacuvuvame go, se zema najdobara i najrelevantana verzija na sekoe parce
        if len(videni) >= settings.candidate_k: # dokolku imam dovolno dobar kandidat
            break   #se prekinuva, ne se bara novo relevanto parce - optimizacija na parceto

    if neuspesi == len(varijanti):  # dokolku site varijanti padnat, ne samo edna
        raise RetrievalUnavailable("Пребарувањето е недостапно (Qdrant/embeddings)")    # bazata e nedostapna i frla errors
    kandidati = sorted(videni.values(), key=lambda pogodok: pogodok["score"],reverse=True) # se sortiraat site unikatni kandidati po niven score, opagacki (najrelevantnite prvo)
    kandidati = kandidati[: settings.candidate_k]   # se zemaat samo top kandidatite, ovie odat na rerank
    if not kandidati:   # dokolku nema nitu eden kandidat, ama bazata rabote, samo nema sovpaganje
        return []   # se dava prazno, nema informacija
    oceni = reranker.rerank(prashanje, [kand["text"] for kand in kandidati]) # rerenak dava na cross encoderot samo tekovnite 20 kandidati , vraka ocenka od 0 do 1 ili none ako rerank ne e dostapen
    if oceni is not None: #dokolki rerenk raboti (ne e none)
        for kandidat, ocena in zip(kandidati, oceni, strict=True):  # spojuvame go sekoj kandidat so negovata ocenka, string = Ture ako dolzinite ne se isti dava greska 
            kandidat["rerank_score"] = ocena    # se zapisuva ocenkata vo kandidat 
        kandidati = [kandidat for kandidat in kandidati # se zadrzuvaat site onie nad pragot
                     if kandidat["rerank_score"] >= settings.rerank_threshold] # gi trgame site parcinja koj so e slabo relevantni a se pronajdeni
        kandidati.sort(key=lambda kand: kand["rerank_score"], reverse=True) # sortiranje po rerak ocena, ako rerank padne ili ocena e none se razdrazuva orginalniot redosled od serach

    najdobri = kandidati[: settings.top_k]  # se zemaat samo najrelevantite parcinja, se prakaat do LLM 
    logger.info("Retrieval: %d кандидати → %d по rerank/threshold", len(videni), len(najdobri))
    return najdobri # go vrakam finalnoto prace koa ima najdobar odgovor

def extract_sources(parchinja: list[dict]) -> list[dict]:   # zema uniktni izvori za prikaz kako naslov, link clen
    izvori, videni_klucevi = [], set()  # lista za rezultato i dopolnitelno set za sledenje stp veke imame dodadeno
    for parche in parchinja:   #pomini niz sekoe parce
        podatoci = parche.get("payload", {})   # zemame prazen recnik
        kluc = (podatoci.get("source"), podatoci.get("article_no")), #kluc za uniktnost, dva clena od ist dokument se razlicni izvori, no ist cel dvapati ke ni e duplikat
        if kluc in videni_klucevi:  # dokolku go imeme dodadeno 
            continue    # se preskoknuva se dodeka ne se pronajde nekoj sto ne e pronajden 
        videni_klucevi.add(kluc)   # se oznacuva kako dodaden vo bazata
        izvori.append({ # se dodava vo forma koja e razbirliva za widgetot na frontend delot
            "title": podatoci.get("title") or podatoci.get("source") or "?",    # naslov ili souce
            "url": podatoci.get("url"), # link od kade e najdeno 
            "article_no": podatoci.get("article_no"),  # se dava clenot od koj e pronajden odgovorot ili parceto so se prikazuva
            "source": podatoci.get("source") or "?",    # se dava izvorniot fajl ili URL ako e najdeno na net 
        })
    return izvori # se vraka listata na unikatnii izvori za odgovorot
