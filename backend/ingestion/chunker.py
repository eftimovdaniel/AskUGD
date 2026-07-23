# poradi toa so oficijalnite dokumeti se nogu dolgi, ne e logicno da se praka celiot dokumet na LLM, nitu da se cuva
# kako eden vektor, zatoa go secam na delovi so priblizna golemina od 800 do 1000. Sekoe preseceno parce go pravam vektor za da
# go smstam vo bazata

from __future__ import annotations
import re
from dataclasses import dataclass, field

ARTICLE_RE = re.compile(r"(?m)^\s*(Член\s+\d+[а-я]?)\b")   #Regez sto bara Clen, broj ili bukva na ^ pocetokot na sekoj red a so \b granicata na zboro 
MAX_WORDS = 1000   #max dolzina na zborot, sekoe parce nad 1000 se seca da bide tocno 1000 zbora
OVERLAP_RATIO = 0.15  #preklopuvanje, dokolku se isece na granicata, da ne se izgube sosedniot del od tekstot
                      # ...rokot e 15 septemvri" padne tochno na kraj od edno parche, so preklop taa recenica se pojavuva i na pochetok od slednoto — pa prebaruvanjeto ja faka bez razlika koe parche go najde.
PARAGRAPH_TARGET = 800 # goleminata na celoto parce da bide 800 
MIN_CHUNK_WORDS = 8 # parce pomalo od 8 zbora se otfrla najcesto e nekoj sum

_INJECTION_RE = re.compile( #Regex za sprecuvanje na promt injdestions vrazi vo dokumentavijata 
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
class Chunk:    #edno parce od tekst i metapodatoci
    text: str   # tekstot na parceto
    metadata: dict = field(default_factory=dict)   #metapodatokot, broj na artikol, sekcija, izvor

def neutralize_injections(text: str) -> str:    # se koriste za noramalizacija, zamenuva injection frazi vo bezopasen tekst 
    return _INJECTION_RE.sub("[отстранета инструкција]", text)

def _split_by_words(text: str, maks_zborovi: int = MAX_WORDS) -> list[str]:
    zborovi = text.split()  # razdeleni zborovi
    if len(zborovi) <= maks_zborovi:  # proverka na dolzinata, ako e dovolno mal 
        return [text]   # se vraka celiot bez da se sece
    preklop = max(0, int(maks_zborovi * OVERLAP_RATIO)) #proverka kolku zborovi se preklopuvaat
    cekor = max(1, maks_zborovi - preklop)  
    delovi, pozicija = [], 0 #rezlutat i pocetna pozicija
    while pozicija < len(zborovi): #dvizenje niz zborot
        delovi.append(" ".join(zborovi[pozicija:pozicija + maks_zborovi]))  #zemame parce od pozicijata i go spojuvame vo string
        if pozicija + maks_zborovi >= len(zborovi): # dokolku se dostigne kraj
            break   # se prave prekin da ne se povtori poslednoto
        pozicija += cekor   # pomesti se za sekoj cekor 
    return delovi

def _chunk_by_articles(text: str) -> list[Chunk]:   # secenje po clenovi vo dokumentot, sekoj se odvojuva i ne se gube kontekst 
    sovpaganja = list(ARTICLE_RE.finditer(text))    # naogame gi site clen pozicii
    parchinja: list[Chunk] = [] 
    if sovpaganja and sovpaganja[0].start() > 0:    #dokolku ima voved ili nekoj drug tekst pred clen 
        voved = text[:sovpaganja[0].start()].strip()    # se zema i se pretvara i toj vo clen
        if len(voved.split()) > 20: #proverka ako e dovolno dolg na primer 20 karakteri se zema onaka ne poso nema da ima nogu informacii
            for del_br, delce in enumerate(_split_by_words(voved)): # dokolku vovedot e golem se sece, sekoj del e parce
                parchinja.append(Chunk(delce, {"article_no": None, "section": "вовед", "part": del_br}))    
    for indeks_sovp, sovpaganje in enumerate(sovpaganja):   # pominuvame niz sekoj clen 
        pocetok = sovpaganje.start()  #pocetok na ovoj clen
        kraj = (sovpaganja[indeks_sovp + 1].start() #kraj na cleot, so toa se dava znaenje deka imam voved na nov clen sto treba da se zeme 
               if indeks_sovp + 1 < len(sovpaganja) else len(text)) #ili kraj na tekstot ne se zima niso ako e poselden cel od dokumentot
        telo = text[pocetok:kraj].strip()   # go smesuvame telot na cleno, od pocetok do kraj so ima napisno kako tekst vo clenot 
        oznaka = sovpaganje.group(1).strip()    # oznaka na clenot 
        for del_br, delce in enumerate(_split_by_words(telo)):  # dokolku clenot e nogu dolg, go deleme na podclenovi i sekoj podclen nosi ista ozaka za da se znae deka idat od isti clen
            parchinja.append(Chunk(delce, {"article_no": oznaka, "part": del_br}))  
    return parchinja

def _chunk_by_paragraphs(text: str) -> list[Chunk]: #se sece po pasusi, se ignorira clenovi, proceduri, naslovi
    surovi_pasusi = [pasus_edinica.strip() for pasus_edinica in text.split("\n\n") if pasus_edinica.strip()]    #se rezdeluvaat po noval linija i se trgat praznite mesta 
    pasusi: list[str] = []
    for pasus_edinica in surovi_pasusi: #osigruvanje deka niru eden pasus ne e pogolem od pogolem 
        pasusi.extend(_split_by_words(pasus_edinica))  # # dokolku pasusot e golem se sece po zborovi

    parchinja: list[Chunk] = [] 
    bafer: list[str] = [] #bafer vo koj se smesteni site pasusi dodeka ne se celosno ispolne 
    broj_zborovi, sekcija_br = 0, 0 #broi zborovi vo baferot i reden broj na sekcijata od kade ide pasusot 
    for pasus in pasusi:    #pominuvanje niz site pasusi
        zborovi_pasus = len(pasus.split())  #gledame kolku zborovi ima sekoj pasus 
        if broj_zborovi + zborovi_pasus > PARAGRAPH_TARGET and bafer:   #ako dojdovniot pausus bi go nadminal targetot i baferot ne e prazen, nema da moze da se smeste vo nego
            parchinja.append(Chunk("\n\n".join(bafer), {"section": f"дел {sekcija_br}"}))   #se zemaat site pasusi od bafeto gi spojuvame vo prazen red megu niv, 
                                                                                            #i se prave novo parce so oznaka del N i se dodava vo listata na gotovi pracinja
            sekcija_br += 1       #sledna sekcija dobiva nov broj
            posleden_pasus = bafer[-1]  # za da imame preklop se zema posledniot pasus od baferot 
            if len(posleden_pasus.split()) <= PARAGRAPH_TARGET // 2:    # dokolku e mal
                bafer = [posleden_pasus]    #noviot bafer pocnuva so nego so toa imame preklop
                broj_zborovi = len(posleden_pasus.split())
            else:   #dokolku pasusot e pregolem 
                bafer, broj_zborovi = [], 0 #bafero go stavame da e prazen i se zapocnuva so tekovnite prrcinja 
        bafer.append(pasus) #se dodava tekovniot pasus
        broj_zborovi += zborovi_pasus   #update na broj_zborovi 
    if bafer:   #dokolku ostane nesot vo baferot
        parchinja.append(Chunk("\n\n".join(bafer), {"section": f"дел {sekcija_br}"}))   # se spojuvat vo posledno parce
    return parchinja

#glavna funkcija se povikuva od run_infestion
def chunk_document(text: str, source: str, doc_type: str = "pdf", title: str | None = None, url: str | None = None, lang: str = "mk",) -> list[Chunk]:
    if not text or not text.strip():    #dokolku ne e pronajden tekst 
        return []   #se vraka prazna lista
    text = _CONTROL_RE.sub("", text)    # cistenje na nevidlivite karakteri 
    ima_clenovi = len(ARTICLE_RE.findall(text)) >= 3  #izbroj "Clen N". Ako 3+ = pravilnik = sechi po clenovi, 3: eden-dva mozat da se sluchajna referenca; 3+ znaci strukturiran praven dokument.
    parchinja = _chunk_by_articles(text) if ima_clenovi else _chunk_by_paragraphs(text) # se prima izbranata strategija
    rezultat: list[Chunk] = []  #smestuvanje na finalnite parcinja 
    for parche in parchinja: # se mine niz sekoe surovo parce 
        if len(parche.text.split()) < MIN_CHUNK_WORDS:  # dokolku e pomalo od 8 zbora
            continue    # se preskoknuva i se ode na sledno parce
        parche.text = neutralize_injections(parche.text)    # neutralizacija na frazite, da se namale sansata za napad
        parche.metadata.update({    #dodavanje na matedate
            "source": source,   # ime na fajlit ili url od kade ide informacijata  
            "title": title or source,   #naslov ili source ako nema
            "url": url,     #link so ke se pokazuva na widget na frontend delot 
            "doc_type": doc_type,   # dali info e od pdf ili web
            "lang": lang,   # jazik 
            "chunk_index": len(rezultat),   # reden broj po filtriranje        
            "strategy": "article" if ima_clenovi else "paragraph",  # koja strategija e koristena, delenje na tekstot kako paragraf artikol ili slicno
            "word_count": len(parche.text.split()), # kolku zborovi se izvleceni za eval da vidam dali se vlecat zborovi od znaenjeto vo terminalot
        })
        rezultat.append(parche) #dodavanje vo gotovot parce
    return rezultat #davanje na listata na gotovi prarcinja za zapis vo qdrant
