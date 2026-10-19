# Detekcija na jazik i evtina mk-latinica → кирилица (bez LLM).
# langdetect često ja meša mk-латиницата со hr/sr; zatoa prvo gledame mk znaci.
from __future__ import annotations
import re

CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# Funkciski zborovi što studentite gi pišuvaat so latinica.
_MK_FUNC = re.compile(
    r"(?i)\b(kolku|koga|kako|kade|shto|sto|dali|treba|cini|chini|"
    r"jas|nie|vie|moze|mozam|sakam|ima|nema|koj)\b"
)
# Akademski termini od UGD dokumentite.
_MK_TERMS = re.compile(
    r"(?i)\b(upis|zaverka|stipend|semestar|ispit|kolokvium|fakultet|"
    r"ugd|indeks|prijava|prijavam|kredit|partici|skolarina|dosie|"
    r"ciklus|predmet|rok|rokovi|dokument)\b"
)
# Ako gi ima ovie, po-verojatno e angliski, ne mk-латиница.
_EN_FUNC = re.compile(
    r"(?i)\b(the|how|what|when|where|does|do|please|can|could|"
    r"would|my|your|this|that|with|from|about|enroll|enrollment)\b"
)
_SOUTH_SLAVIC = {"hr", "sr", "bs", "sl", "bg", "mk"}

# Celi zborovi pred bukva-po-bukva (cini≠цини, cena≠чена).
_TERMS = {
    "upis": "упис", "upisot": "уписот", "upisam": "упишам",
    "zapisham": "запишам", "zapisi": "запиши",
    "zaverka": "заверка", "zaverkata": "заверката",
    "stipendija": "стипендија", "stipendii": "стипендии",
    "kredit": "кредит", "krediti": "кредити",
    "semestar": "семестар", "semestarot": "семестарот",
    "kolokvium": "колоквиум", "kolokviumi": "колоквиуми",
    "ispit": "испит", "ispiti": "испити", "ispiten": "испитен",
    "fakultet": "факултет", "fakulteti": "факултети",
    "ugd": "угд",
    "particiacija": "партиципација", "participacija": "партиципација",
    "skolarina": "школарина",
    "cena": "цена", "cenata": "цената",
    "rok": "рок", "rokovi": "рокови", "rokot": "рокот",
    "predmet": "предмет", "predmeti": "предмети",
    "indeks": "индекс", "dosie": "досие",
    "prijava": "пријава", "prijavam": "пријавам", "prijavuvanje": "пријавување",
    "ciklus": "циклус",
    "kolku": "колку", "koga": "кога", "kako": "како", "kade": "каде",
    "shto": "што", "sto": "што", "dali": "дали",
    "cini": "чини", "chini": "чини",
    "treba": "треба", "mozam": "можам", "moze": "може",
    "dokumenti": "документи", "dokument": "документ",
    "student": "студент", "studenti": "студенти",
    "studiranje": "студирање", "studii": "студии",
    "prv": "прв", "vtor": "втор", "tret": "трет",
    "na": "на", "od": "од", "za": "за", "so": "со",
    "da": "да", "se": "се", "vo": "во", "gi": "ги", "go": "го",
    "mi": "ми", "ti": "ти", "i": "и", "e": "е", "ne": "не",
}

# Redosledot e biten — zamenite tecat edna po druga: „dzh“ mora pred „zh“ i „dz“,
# inaku „dzh“ prvo bi stanalo „dж“ i nikogas ne bi se sklopilo vo „џ“.
_DIGRAFI = (
    ("dzh", "џ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"),
    ("gj", "ѓ"), ("kj", "ќ"), ("dj", "ѓ"), ("lj", "љ"),
    ("nj", "њ"), ("dz", "ѕ"),
)
_MK_MAP = str.maketrans({
    "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф",
    "g": "г", "h": "х", "i": "и", "j": "ј", "k": "к", "l": "л",
    "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с",
    "t": "т", "u": "у", "v": "в", "z": "з",
    "č": "ч", "ć": "ќ", "š": "ш", "ž": "ж", "đ": "ѓ",
})
# Samo bukvi: brojkite, sifrite i interpunkcijata minuvaat nedopreni niz transliteracijata.
_WORD_RE = re.compile(r"[A-Za-zČĆŠŽčćšžĐđ]+")


def ima_kirilica(tekst: str) -> bool:
    return bool(CYRILLIC_RE.search(tekst or ""))


def is_mk_latin(tekst: str) -> bool:
    if not tekst or ima_kirilica(tekst):
        return False
    if _MK_FUNC.search(tekst):
        return True
    return bool(_MK_TERMS.search(tekst) and not _EN_FUNC.search(tekst))


def _bukvi(zbor: str) -> str:
    nizok = zbor.lower()
    for lat, kir in _DIGRAFI:
        nizok = nizok.replace(lat, kir)
    return nizok.translate(_MK_MAP)


def transliterate_mk(tekst: str) -> str:
    def zamena(sovpaganje: re.Match[str]) -> str:
        zbor = sovpaganje.group(0)
        kluc = zbor.lower()
        if kluc in _TERMS:
            return _TERMS[kluc]
        return _bukvi(zbor)

    return _WORD_RE.sub(zamena, tekst)


def detect_language(prashanje: str) -> str:
    tekst = (prashanje or "").strip()
    if ima_kirilica(tekst):
        return "mk"
    if is_mk_latin(tekst):
        return "mk"
    try:
        from langdetect import DetectorFactory, detect
        DetectorFactory.seed = 0
        kod = detect(tekst)
    except Exception:
        return "und"
    if kod in _SOUTH_SLAVIC and _MK_TERMS.search(tekst):
        return "mk"
    return kod


# Nepoznato ili sosedno-slovensko → MK: vidzetot stoi na makedonski sajt, pa
# mk-latinicata sto langdetect ja cita kako „hr“/„sl“ ne smee da dobie angliski.
_KON_MK = _SOUTH_SLAVIC | {"sk", "cs", "ru", "uk", "und"}


def pick_lang(prashanje: str, dostapni) -> str:
    """Jazik za fiksna poraka: tocen kod ako go imame, inaku mk/en spored blizina."""
    kod = detect_language(prashanje)
    if kod in dostapni:
        return kod
    return "mk" if kod in _KON_MK else "en"
