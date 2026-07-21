from __future__ import annotations
import logging
import math
from app.config import settings

logger = logging.getLogger(__name__)
_encoder = None # globalna promeliva za modelot, none znaci deka modelot ne e vcita, staveno e none za da moze da se vcita samo ednas, da ne se vcituva pri sekoe aktiviranje
_load_failed = False #znamenca, proverka dali vcituvanjeto porpadnalo, dokolku ne uspee da ne se probuva pri sekoe postaveno prasanje

def _get_encoder():
    global _encoder, _load_failed   # global ke gi menuva globalnite promenlivi, ne da se sozdavaat lokalno
    if _encoder is None and not _load_failed: # se vcituva samo dokolku pregthodno ne e vcitano i prethodno ne propadnalo, i kako uslov se zema da ne se obiduvame povtorno
        try:    # dokolku vcituvanjeto padne, nemame dovolno memorija ili internet 
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            logger.info("Вчитувам reranker %s ...", settings.rerank_model)
            _encoder = TextCrossEncoder(model_name=settings.rerank_model)  #sozdavanje na modelot, se simnuva ako go nema kesirano, se pravi samo ednas na pocetokot
        except Exception as greshka:  # pri nastanuvanje na pad
            _load_failed = True # oznacuvame deka nastalan pad
            logger.error("Reranker не се вчита (%s) — продолжувам без rerank", greshka) # log za da vidam dali e uspesno ili ne 
    return _encoder # se vraka modelot ili dava None ako propadne 

def rerank(prashanje: str, dokumenti: list[str]) -> list[float] | None: #glavna funkcija vraka ocena od 0 ... 1 za sekoj dokument ili none ako reran ne e dostapno
    if not dokumenti: #dokolku ne e najdena dokumentacija
        return [] #se vraka prazna lista so ocenka, nema sto da se oceni
    enkoder = _get_encoder()    # se zema modelot
    if enkoder is None: # dokolku ne e dostapen 
        return None # se vraka none, povikuvacot fo koristi none kako string, bidejki so [] ke bide deka nema dokumentaicija
    try:    # dokolku ocenuvanjeto padne
        surovi_oceni = list(enkoder.rerank(prashanje, dokumenti)) # modelot ja presmetuva relevantnosta na sekoj dokument spored prasanjeto. 
        return [1.0 / (1.0 + math.exp(-ocena)) for ocena in surovi_oceni]   # se pretvata vo 0..1 so SIGMOID funkcija, SIGMOID gi maprira so verojatnosna skala i e konzistentno
    except Exception as greshka:  # dokolku ocenkata padne
        logger.error("Rerank падна (%s) — продолжувам без rerank", greshka)
        return None # se vraka none na korisnickata strana 
