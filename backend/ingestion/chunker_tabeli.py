from __future__ import annotations
import re   #
import re   #regex — za prepoznavanje naslov, podnaslov, kontrolni znaci
from dataclasses import dataclass, field

TABLE_MAX_WORDS = 350   #max zbora po chunk 
TABLE_MIN_ROWS = 1  #tabela od 1 red, i nea ja koristeme 
_PODNASLOV_RE = re.compile(r"^—\s*(.+?)\s*—$")  #prepoznava red "— ПРВА ГОДИНА —" podnaslov vnatre vo tabela
_MAKS_ZBOROVI_PODNASLOV = 10    #podnaslovot se povtoruva — mora da e kratok so max od 10 zbora
_NASLOV_RE = re.compile(r"^\[.*\]$")    #prepoznavanje naslovna linija
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")   #nevidlivi kontrolni znaci za brisenje

@dataclass
class Chunk:
    text: str   #tekst na parcinja
    metadata: dict = field(default_factory=dict)    #metapodatoci

def _zaglavna_linija(koloni: list[str]) -> str: #pravi linija
    if not koloni:  #ako nema koloni
        return ""   #prazno
    return "Колони: " + ", ".join(koloni)   #inaku nabroj gi kolonite

def _iseci_dolg_red(red: str, maks_zborovi: int) -> list[str]:  #secen red sto sam e podloga od limitot
    zborovi = red.split()   #zborovite na redot
    if len(zborovi) <= maks_zborovi:    #dokolku e dovolno kratko
        return [red]    #vrati go kako sto e
    if " | " in red:    #ako ima Kolona | Kolina struktura
        prefiks = red.split(" | ", 1)[0]    #prefiks = prviot del 
    else:   #inaku
        prefiks = " ".join(zborovi[:8]) #zemanje na prvite 8 zborovi kako prefiks
    prefiks = " ".join(prefiks.split()[:12])    #skrati go prefiksot na max 12 zbora (za da ne e ogromen)
    rezerva = len(prefiks.split()) + 2  #kolku mesto zafakja prefiksot + 2
    cekor = max(20, maks_zborovi - rezerva) #kolku zbora po parche barem 20
    parcinja = []   #rezultati
    for pocetok in range(0, len(zborovi), cekor):   #mini niz zborovite so cekor 
        parche = " ".join(zborovi[pocetok:pocetok + cekor]) #zemi parce zborovi
        parcinja.append(parche if pocetok == 0 else f"{prefiks} (продолжение): {parche}")   #prvoto e cel, ostanatite nosat prefiks
    return parcinja #vrati gi parcinjata

def _presmetaj_delovi(redovi: list[str], maks_zborovi: int) -> list[list[str]]: #grupira redovi vo delovi <= limit
    delovi: list[list[str]] = []    #gotovite delovi
    tekoven: list[str] = [] #redovite vo tekovniot del
    broj_zborovi = 0    #sobira zborovi vo tekovnite delovi
    for surov_red in redovi:    #minuva niz sekoj red
        for red in _iseci_dolg_red(surov_red, maks_zborovi):    #dokolku e predolg se sece
            zborovi_red = len(red.split())  #kolku zbora ima ovoj red
            if broj_zborovi + zborovi_red > maks_zborovi and tekoven:   #ako bi go prefrlil limitot i imame sobrano
                delovi.append(tekoven)  #zatvaranje na tekovnite delovi
                tekoven, broj_zborovi = [], 0   #pocnuvanje nov ptazen del 
            tekoven.append(red) #dodavanje vo redot
            broj_zborovi += zborovi_red #update na brojot na zborovi
    if tekoven: #dokolku ostane nesto
        delovi.append(tekoven)  #dodavanje na posledniot del
    return delovi   #vrati gi delovite

def _posleden_podnaslov(redovi: list[str]) -> str | None:   #pronaoganje na podnaslov vo delot
    for red in reversed(redovi):    #se ode od nazad kon nanapred
        sovpaganje = _PODNASLOV_RE.match(red)   #dali redot e podnaslov
        if sovpaganje:  #ako e 
            kandidat = sovpaganje.group(1).strip()  #se vadi teksto megu crtickite
            if len(kandidat.split()) <= _MAKS_ZBOROVI_PODNASLOV:    #ako e kratko, ne e pasus
                return kandidat #vrati go 
    return None #ne e pronajden podanslov

def chunk_table_blocks(blokovi,source: str,doc_type: str = "pdf",title: str | None = None,url: str | None = None,lang: str = "mk",neutralize=None,) -> list[Chunk]:  #TableBlock -> Chunk-ovi
    rezultat: list[Chunk] = []  #gotovi parcinja
    for tabela_br, blok in enumerate(blokovi):  #minuvanje niz sekoja tabela
        site_linii = [l for l in blok.text.splitlines() if l.strip()]  
        if not site_linii: #prazna tabela
            continue
        if _NASLOV_RE.match(site_linii[0]): #ako prvata linija e секција, страна N, член
            naslov_linija, redovi = site_linii[0], site_linii[1:]  #odvojuvanje na naslov od redovi
        else:
            naslov_linija, redovi = "", site_linii  #nema naslov, se e redovi
        if len(redovi) < TABLE_MIN_ROWS:    #premalku redovi
            continue    #preskoknuvanje
        zaglavje = _zaglavna_linija(blok.columns)   #napravi Koloni:... linija  
        rezerva = (len((naslov_linija + " " + zaglavje).split())+ _MAKS_ZBOROVI_PODNASLOV + 3)  #mesto sto go zafakjaat naslov koloni i podnaslovi
        buxhet = max(50, TABLE_MAX_WORDS - rezerva) #kolku zbora ostanuvaat za redovite
        delovi = _presmetaj_delovi(redovi, buxhet)  #razdeli gi redovite vo delovi
        vkupno_delovi = len(delovi) #kolku delovi
        prenesen_podnaslov: str | None = None   #podnaslovot sto se prenesuva vo sledniot del
        for del_br, del_redovi in enumerate(delovi):    #minuva niz sekoj del
            glava = [linija for linija in (naslov_linija, zaglavje) if linija]  #vo glava se cuva naslov i kolona dokolku gi ima
            if del_br > 0 and prenesen_podnaslov:   #ako ne e prviot del i imame podnaslov sto se prenesuva
                glava.append(f"— {prenesen_podnaslov} (продолжение) —") #dodavanje na vrvot na prarceto
            tekst = "\n".join(glava + del_redovi)   #spoi glava + redovite vo eden tekst
            tekst = _CONTROL_RE.sub("", tekst)  #otstranuvanje na nevidliv znaci
            if neutralize is not None:  #ako e dadena zastita od injection
                tekst = neutralize(tekst)   #neutralizacija na injection frazi
            rezultat.append(    #chunk i dodavanje
                Chunk(
                    tekst,
                    {
                        "source": source,   #ime na fajlovi ili URL
                        "title": title or source,   #naslv ili source ako nema
                        "url": url, #link za prikaz na frontend del
                        "doc_type": doc_type,   #pdf ili web
                        "lang": lang,   #jazik
                        "chunk_index": len(rezultat),  #reden broj na parceto vo celata lista
                        "content_type": "table",    #tabelata
                        "strategy": "table",    #na koj nacin e obrabotena
                        "section": blok.section,    #naslov nad tabela ako ima
                        "columns": blok.columns,    #iminja na koloni
                        "page_start": blok.page_start,  #pocetna strana
                        "page_end": blok.page_end,  #posledna 
                        "table_index": tabela_br,   #koja tabela po red e vo dokumentacijata
                        "part": del_br, #koj del od tabelata e dadenoto parce
                        "n_parts": vkupno_delovi,   #kolku delovi se izvleceni
                        "n_rows": len(del_redovi),  #kolku redovi vo dodadeno parce
                        "word_count": len(tekst.split()),   #kolku zborovi- se koriste za proverka na limioto na zborovi
                        "extraction_method": blok.metadata.get( #koj metod e koriste za da se dobijat vie infromacii
                            "extraction_method", "pdfplumber"
                        ),
                    },
                )
            )
            nov = _posleden_podnaslov(del_redovi)   #dali ima podanslov na krajot od ovoj del
            if nov: #ako ima
                prenesen_podnaslov = nov    #go pameti za sledniot del
    return rezultat #vrakanje na site chunk ovi
