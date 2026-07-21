from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from app.config import settings
from app.core.generator import get_llm_client

logger = logging.getLogger(__name__)
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]") #Regex sto bara bilo koj kirilicen karakter. od e do ж gi pokriva site kirilicni buvki vo unicode. Se kompajlirat samo ednas

def needs_translation(question: str) -> bool: # se donesuva odluka dali na prasanjeto mu e potrebno prevod ili pak ne
    return not _CYRILLIC_RE.search(question) #se prebatuva dali ima nekoja kirilicna bukva ako nema ne se preveduva, dokolku se najde se preveduva

@dataclass
class TranslationResult:    # rezlutat od obidot za prevod
    translated: str | None #prevod ili none 
    attempted: bool # dali ima obid za prevod ili ne 

def translate_query(question: str) -> TranslationResult:   #funkcija koja preveduva prasanja na makedonski
    if not needs_translation(question): # dokolku prasanjeto e na kirilica (postaveno na makedosnki)
        return TranslationResult(translated=None, attempted=False)  # odluka - nema potreba od prevod 
    try:
        client = get_llm_client()   # se zema LLM klientot 
        resp = client.chat.completions.create(  # se povikuva llm za prevod 
            model=settings.llm_model,   # se koriste istito kako za generiranje na odgovor
            messages=[  # se definiraat dve poraki, edna za instrukcija i prasanje
                {"role": "system",
                 "content": "Translate the user's question to Macedonian. ""Return ONLY the translation, nothing else."},
                {"role": "user", "content": question},
            ],
            temperature=0.0,    # nejdeterministricki prev, se zema onoj sto e najdosleden, ne e potreba nekakva varicjacija
            max_tokens=200, # definiranje limit na tokenot, prevodot ne treba da bide razdolzen, vaka so limit ke imame prevod koj nema da trosi nogu tokeni(a so toa i pari)
        )
        translated = (resp.choices[0].message.content or "").strip()   # se vade prevod, ' or "" zastita dokolku e none, so strip() se prisat prazni mesta
        return TranslationResult(translated=translated or None, attempted=True) # se vraka prevodot, dokolku translated or None e prazen string se pretvara vo none  
    except Exception as error:  #dokolku prevodot padne 
        logger.warning("Преводот на прашањето падна (модел=%s): %s", settings.llm_model, error)
        return TranslationResult(translated=None, attempted=True) # vrati none i attempted true, prevodot e podovruvanje ako padne retriver prodolzuva so orginalnoto prasanje. 