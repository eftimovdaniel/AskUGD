#nova verzija na vaj fajl
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
import pdfplumber   #citanje na tabeli od pdf, gi gleda koordinatite na sekoja kelija

logger = logging.getLogger(__name__)
_MIN_PREKLOP = 0.30 #30% od sirinata sto dve kelii mora da se preklopat po X za ista kolona
_MAKS_ZAGLAVNI_REDOVI = 6   #maksmum 6 reda od vrvot se gleda koga barame zaglavje

@dataclass  
class TableBlock:   #kontejner za izvlecena tabela
    text: str   # citliviot tekst koj e izvlecen
    section: str    #naslov nad tabelata    
    page_start: int #prvata stranica na tabelata
    page_end: int   # poslednata stranica na tabelata
    n_rows: int #broj na redovi so podatoci
    columns: list[str] = field(default_factory=list)   #iminja na kolonite 
    metadata: dict = field(default_factory=dict)    #dopolnitelni metadata

def _redovi_so_pozicii(tabela) -> list[list[tuple[float, float, str]]]: #za sekoja tabela vraka kelija
    try:    #extract moze da padne na nekoj tabeli
        mreza = tabela.extract()    #mreza gi zema tekstovite na site tabeli odednas
    except Exception:   #dokolku padne
        return []   #se vraka prazna lista za da ne se rusi ostaokot 
    izlez: list[list[tuple[float, float, str]]] = []    #vo izlez se sobirat redovite
    for red_obj, red_tekst in zip(tabela.rows, mreza):  #se sparuva pozicii so tekst vo red
        kelii = []  #kelija na ovoj red
        for kelija, tekst in zip(red_obj.cells, red_tekst): #spojuvanje na pozicija na kelija so nejziniot tekst
            if kelija is None or not tekst: #dokolku vo kelijata nema tekst 
                continue    #se preskoknuva
            x0, _t, x1, _b = kelija #od (x0,top,x1,bottom) ni trebaat samo levo/desno
            cist = str(tekst).replace("\n", " ").strip()    #spojuvanje na prekin vo eden red i trganje prazni mesta
            if cist:    #dokolku ostane nesto
                kelii.append((x0, x1, cist))    #se zapisuva kelijata so pozicii
        if kelii:   #dokolki redot ima barem edna polna kelija
            izlez.append(kelii) #se dodava vo redot
    return izlez    #vrakanje na site redovi so pozicii 

def _preklop(a0: float, a1: float, b0: float, b1: float) -> float:  #kolku dve X-granici se preklopuvaat (0..1)
    presek = min(a1, b1) - max(a0, b0)  #dolzinata na zaednickiot del
    if presek <= 0: #ako nema presek
        return 0.0  #nema preklopuvanje 
    najmala_sirina = min(a1 - a0, b1 - b0) or 1.0   #sirinata na poresniot interval
    return presek / najmala_sirina  #del od potesniot sto se preklopuva

def _e_red_so_podatoci(kelii: list[tuple[float, float, str]]) -> bool:  #proverka dali redot e podatok, a ne zaglavje
    if not kelii:   #dokolku e prazen red
        return False    #ne e podatok
    tekstovi = [t for _, _, t in kelii] #vadenje na samo tekstovite
    ima_cifra = any(any(c.isdigit() for c in t) for t in tekstovi)  #proverka dali ima barem edna cifra vo redot
    return ima_cifra    #red so cifra = podatok inaku bez cifra = zaglavie

def _spoi_ime(delovi: list[str]) -> str:    #spojuvanje delovi na ime bez povtoruvanje
    videni: list[str] = []  #unikatni fragmenti po redosled
    for del_ in delovi: #minuvanje niz delovite
        if del_ not in videni:  #dokolku imame insti framgment 2pati
            videni.append(del_) #se zadrzuva samo onoj sto e dobien od prviot at
    zborovi, izlez = set(), []  #set za videni zborovi,  lista za rezultatv
    for zbor in " ".join(videni).split():   #spojuvanje na delovite, a posle spojuvanje vo zborovi
        if zbor.lower() not in zborovi: #dokolku zborot ne e najden prethodno
            zborovi.add(zbor.lower())   #go pameti
            izlez.append(zbor)  #i go dodava vo rezultatot
    return " ".join(izlez).strip()  #vrati go spoeneto ime

_MAKS_ZNACI_IME_KOLONA = 60 
_MAKS_ZBOROVI_IME_KOLONA = 8

def _e_ime_na_kolona(tekst: str) -> bool:  #proverka dali fragmentot moze da bide ime na nekoja kolona
    cist = tekst.strip()    #trganje na prazni mesta
    if not cist:    #prazno 
        return False    #ne e ime 
    return (len(cist) <= _MAKS_ZNACI_IME_KOLONA and len(cist.split()) <= _MAKS_ZBOROVI_IME_KOLONA)  #dokolku e kratko toa e ime, inaku toa ni e sodrzina

def _spoi_zaglavie(zaglavni_redovi: list[list[tuple[float, float, str]]]) -> list[tuple[float, float, str]]:   #rasprsnati zaglavja -> koloni po X
    koloni: list[dict] = [] #sobranite koloni
    for red in zaglavni_redovi: #minuva niz zaglavenite redovi
        for x0, x1, tekst in red:   #minuvanje niz sekoj zaglaven fragment
            if not _e_ime_na_kolona(tekst): #dokolku e pasus ne e etiketiran
                continue    #se preskoknuva
            sirina = x1 - x0    #sirinata na fragmentoto
            roditel = None  #dali ima postoecki koloni  
            for k in koloni:    #sporedi so vekje sobranite koloni
                if _preklop(x0, x1, k["x0"], k["x1"]) < _MIN_PREKLOP:   #dokolku ne se preklopuvaat dovolno
                    continue    #se preskoknuva
                sirina_k = k["x1"] - k["x0"]    #sirinata na postoeckata kolona
                if sirina < sirina_k * 0.6: #dokolku e pomala
                    roditel = k #se zema kako pod kolona
                    break   #prekin
                k["delovi"].append(tekst)   #dokolku se so slicna sitina -> ista kolona i go dodavame delot
                k["x0"] = min(k["x0"], x0)  # prosiruvanje na levata granica
                k["x1"] = max(k["x1"], x1)  #prosiruvanje na desnata granica
                roditel = "spoena"  #oznaci deka e spoeno vo postoekckata
                break   
            if roditel is None: #ne e pronajdena nikakva kolona
                koloni.append({"x0": x0, "x1": x1, "delovi": [tekst]})  #sosema nova kolona
            elif roditel != "spoena":   #inaku ako e najdena toa e pod kolona
                ime_roditel = _spoi_ime(roditel["delovi"])  #imeto na roditelot 
                koloni.append({"x0": x0, "x1": x1, "delovi": [ime_roditel, tekst]}) #
    koloni.sort(key=lambda k: k["x0"])  #podreduvanje na kolonite od levo kod desno po X
    if len(koloni) < 2: #edna kolona ne e zaglavie 
        return []
    return [(k["x0"], k["x1"], _spoi_ime(k["delovi"])) for k in koloni] #vrakanje na (x0,x1,ime) za sekoja kolona

def _red_vo_tekst(kelii: list[tuple[float, float, str]],koloni: list[tuple[float, float, str]]) -> str:
    parcinja = []   #delovite na redot
    for x0, x1, vrednost in kelii:  # minuva niz sekoja kelija vo koja ima podatok
        najdobra, najtesna_sirina = None, float("inf")  #najdobrata kolona so nejzinata sirina
        for kx0, kx1, ime in koloni:    #sporeduvanje so sekoja kolona
            if _preklop(x0, x1, kx0, kx1) < _MIN_PREKLOP:   #ako nemame dovolno preklopuvanje
                continue    
            sirina = kx1 - kx0  #se zema sirinata na kolona
            if sirina < najtesna_sirina:    #se zema najtesnata sirina
                najdobra, najtesna_sirina = ime, sirina #taka pod-kolonata ja fakja vrednosta, ne roditelot
        najdobar_preklop = 1.0 if najdobra else 0.0 #proveri dali e pronajden kolina
        if najdobra and najdobar_preklop >= _MIN_PREKLOP:   #ako e pronajdena
            if re.fullmatch(r"\d{1,3}\.?", vrednost) and "бр" in najdobra.lower(): #cist reden broj vo kolona 'Ред. бр.' 
                continue
            parcinja.append(f"{najdobra}: {vrednost}")  #zapisi Kolona vrednost
        else:
            parcinja.append(vrednost)   #dodavanje na vrednosta kako sto e
    return " | ".join(parcinja) #spojuvanje so |

def _naslov_nad_tabelata(linii_na_stranica, tabela) -> str | None:  #linijata nad tabelata
    try:
        _x0, top, _x1, _bot = tabela.bbox   #gornata granica na tableata
        kandidati = [ linija for linija in linii_na_stranica if linija["bottom"] <= top + 2 and 0 <= top - linija["bottom"] < 60 ]  #se zemaat site do 60 pt nad tabelata
    except Exception:   #nastane greska
        return None
    if not kandidati:   #dokolku nema linija nad tabelata
        return None
    najbliska = max(kandidati, key=lambda linija: linija["bottom"])["text"].strip() #najbliskata od gornata strana
    if not najbliska or sum(znak.isdigit() for znak in najbliska) > 8:  #dokolku e prazna ili premnogu brojki
        return None #ne e naslov
    return najbliska if len(najbliska) <= 120 else najbliska[:120]     #vrati go

def _najdi_sekcija(page, tabela=None, linii_na_stranica=None) -> str:   #rtikietaa za tabelata
    if tabela is not None and linii_na_stranica:    #ako imame tabela i linija
        nad = _naslov_nad_tabelata(linii_na_stranica, tabela)   #probaj linijata nad tabelata
        if nad: #dokolku najde
            return nad  #vrati ja
    try:    #Inaku se bara naslov na stranicata
        tekst = page.extract_text() or ""   #
        linii = [l.strip() for l in tekst.splitlines() if l.strip()]
        for linija in linii[:5]:    #prvite 5 linii
            if 3 <= len(linija.split()) <= 14 and sum(c.isdigit() for c in linija) < 5: #kratok naslov bez mnogu brojki
                return linija   #vrati ja kako sekcija
    except Exception:   #dokolku padne
        pass
    return "?"  #ako nema naslov ?

def _e_vistinska_tabela(tabela, redovi: list[list[tuple[float, float, str]]]) -> bool:  #filtrira protiv lazni tabeli
    if len(redovi) < 2: #edna linija ne e tabelata
        return False    
    poplneti = sum(len(red) for red in redovi)  #kolku vkupno polni kelii ima 
    if poplneti / len(redovi) < 2.0:    #prosek pod 2 kelii/red = lista, ne tabel
        return False    
    try:
        vkupno_kelii = sum(len(red_obj.cells) for red_obj in tabela.rows) #deklarirana golemina na mrezata
    except Exception:   #dokolku ne moze da se izmeri
        return True
    if vkupno_kelii and poplneti / vkupno_kelii < 0.15:  #pod 15% polnetost = dekorativna mreza
        return False    
    return True #vistinska tabela

def extract_tables(pdf_path, source: str = "") -> list[TableBlock]: #vidi site tabeli od pdf
    blokovi: list[TableBlock] = []  #gotovi tabeli
    tekoven: dict | None = None    #tabeli sto se tekovno sobira
    try:    #dokolku padne pdf pri otvaranje 
        pdf = pdfplumber.open(pdf_path) #otvaranje na pdf ot 
    except Exception as greshka:    #dokolku padne 
        logger.warning("pdfplumber ne moze da otvori %s: %s", source, greshka)
        return []   
    with pdf:   #avtomatsko zatvaranje na pdf na kraj
        for br_stranica, page in enumerate(pdf.pages, 1):   #minenje niz sekoja stranica od pocetok do kraj od 1 
            try:    
                tabeli = page.find_tables() #pronaoganje na tabelite na stranicite
            except Exception as greshka:    #ako padne
                logger.warning("Tabeli na str. %d (%s) padnaa: %s",br_stranica, source, greshka)
                continue    #prodolzuvanje na nova stranica
            try:    #linii se vadat po ednas po stranica
                linii_na_stranica = page.extract_text_lines() if tabeli else [] #
            except Exception:
                linii_na_stranica = [] #prazna lista
            for tabela in tabeli:   #mini niz sekoja tabela na stranicata
                redovi = _redovi_so_pozicii(tabela) #vadenje na redovi so nivna pozicija 
                if not redovi:  #dokolku e prazna tabela
                    continue    #preskoknuvame 
                if not _e_vistinska_tabela(tabela, redovi): #lazna mreza
                    continue    #preskoknuvame
                zaglavni, data_start = [], 0   #zaglavni redovi i kade pocnuvaat podatocite
                for i, red in enumerate(redovi[:_MAKS_ZAGLAVNI_REDOVI]):    #gledaj gi prvite 6 reda
                    if _e_red_so_podatoci(red): #ako naideme na red so cifri
                        break   #podatok imame prekin
                    zaglavni.append(red)    #inaku e zaglaven red
                    data_start = i + 1  #podatocite pocnuvaat posle nego
                data_redovi = redovi[data_start:]   #site redovi so podatoci
                if not data_redovi: #dokolku nema podatoci
                    continue    #preskoknuvanje
                koloni = _spoi_zaglavie(zaglavni) if zaglavni else []   #sostavuvanje na kolonite od zaglavieto
                if not koloni and tekoven is not None:  #dokolku nema svoe zaglavie se prodolzuva na druga tabela 
                    tekoven["data"].extend(data_redovi) #dodavanje na redovite od prethodna tabela
                    tekoven["page_end"] = br_stranica   #prosiruvanje na ovaa stranica
                    continue    #ne otvaraj nova
                if tekoven is not None: #dokolku imame prethodna tabela
                    blokovi.append(_zavrsi(tekoven))    # zatvori ja
                tekoven = {"data": data_redovi, "koloni": koloni,   #otvaranje novi tekovni tabeli
                           "page_start": br_stranica, "page_end": br_stranica,  
                           "section": _najdi_sekcija(page, tabela, linii_na_stranica),  #naslov nad tabelata
                           "source": source}
    if tekoven is not None: #ako imase prethodna tabela
        blokovi.append(_zavrsi(tekoven))    #zatvaranje na istata
    return [b for b in blokovi if b.n_rows > 0] #vrati gi samo tabelite so redovi

def _zavrsi(tekoven: dict) -> TableBlock:   #pretvaranje na sobrani tabeli vo TableBlock
    koloni = tekoven["koloni"]  #kolonite
    linii = []  #gotovi rekstualni redovi
    imenja = {ime.lower() for _, _, ime in koloni}  #set od iminjata na koloni 
    for red in tekoven["data"]:     #minuvanje niz redovite so podatoci
        vrednosti = [t for _, _, t in red]  # samo tekstovite
        if vrednosti and all(len(v) <= 3 and any(v.lower() in i for i in imenja) for v in vrednosti):   #ostatok od zaglavieto
            continue
        if (len(red) == 1 and not any(c.isdigit() for c in red[0][2][:4]) and len(red[0][2].split()) <= 10):    #samostoen podnaslov
            linii.append(f"— {red[0][2]} —")    #zadrzuvame gi kako marker
            continue
        linija = _red_vo_tekst(red, koloni) # pretvori red vo Kolona: vrednost | ...
        if linija:  #ako ima sodrzina
            linii.append(linija)    #dodadi ja
    naslov = f"[{tekoven['section']}, стр. {tekoven['page_start']}" #naslov
    if tekoven["page_end"] != tekoven["page_start"]:    #ako se preleva preku stranici
        naslov += f"–{tekoven['page_end']}" #dodadi go krajot
    naslov += "]"
    imenja_koloni = [ime for _, _, ime in koloni]   #lista od iminjata na kolonite
    return TableBlock(  #sostavuvanje na finalniot blo  k
        text=naslov + "\n" + "\n".join(linii),  #naslov i site redovi
        section=tekoven["section"], #sekcija
        page_start=tekoven["page_start"],   #prva stranica
        page_end=tekoven["page_end"],   #posledna stranica
        n_rows=len(linii),  #broj redovi
        columns=imenja_koloni,  #ime na kolonite
        metadata={"extraction_method": "pdfplumber",    #so koj metod e vadeno
                  "columns": imenja_koloni, #kolonite i vo metadata
                  "source": tekoven.get("source", "")}, #od koj fajlovi ide
    )
