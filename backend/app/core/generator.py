# LLM povik: kontekst, jazik, generacija (cel i token-po-token).
from __future__ import annotations
from functools import lru_cache
from openai import OpenAI
from app.config import settings
from app.core.budget import consume_llm
from app.core.language import detect_language
from app.core.prompts import SYSTEM_PROMPT

# jazichna direktiva: sekogas se dodava na krajot od prasanjeto. Modelot sam go prepoznava jazikot
# na prasanjeto (makedonski so kirilica ili latinica -> odgovor na kirilica; drug jazik -> ist jazik),
# a kontekstot na makedonski NE go menuva jazikot na odgovorot

# Detekcija na jazikot na prasanjeto -> silna direktiva modelot da odgovori na TOJ jazik.
_LANG_NAMES = {  # jasno ne-makedonski jazici -> forsiran odgovor na toj jazik
    "en": "English", "tr": "Turkish", "de": "German", "sq": "Albanian",
    "fr": "French", "es": "Spanish", "it": "Italian",
}


def _lang_directive(prashanje: str) -> str:
    kod = detect_language(prashanje)
    if kod == "mk":
        return "\n\n[ЈАЗИК: Одговори на МАКЕДОНСКИ, со кирилица. Целиот одговор мора да е на македонски.]"
    if kod == "en":
        return ("\n\n[LANGUAGE: Write your ENTIRE answer in ENGLISH. Do not use Macedonian. "
                "The documents are in Macedonian, but your answer must be in English.]")
    ime = _LANG_NAMES.get(kod)
    if ime:
        return (f"\n\n[LANGUAGE: The question is in {ime}. Write your ENTIRE answer in {ime}, not in Macedonian. "
                f"The documents are in Macedonian, but your answer must be in the language of the question.]")
    # nepoznato / transliterirano -> makedonski so latinica odi na kirilica, inaku jazikot na prasanjeto
    return ("\n\n[ЈАЗИК: Одговори на ИСТИОТ јазик како прашањето. Ако прашањето е македонски напишан со латиница, "
            "одговори на македонски со кирилица.]")

@lru_cache(maxsize=1)   #go kesira rezlutatot, so maxsize=1 se presmetuva ednas,potoa sekoe povikuvanje go vraka istiot objekt. Ovo e korisno bidejki openai e skapo pri povikuvanje na sekoe prasanje
def get_llm_client() -> OpenAI:
    if not settings.llm_api_key:   #dokolku klucot ne e pronajden vo settings
        raise RuntimeError("LLM_API_KEY не е поставен во .env") # se dava poraka za nastanatata greska
    return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url,timeout=60.0) # se sozdava klient, so base_url e za menuvanje na provajderot: openai, groq - za da moze da se menuvat bez da se menuva strukturata na celiot kod

def _build_context(parchinja: list[dict]) -> str:   # se zema xml
    delovi: list[str] = []
    potrosheno = 0
    budzet = settings.max_context_chars
    for dok_br, parche in enumerate(parchinja, 1):
        podatoci = parche.get("payload", {})
        oznaka = podatoci.get("title", podatoci.get("source", "?"))
        clen = f" | {podatoci['article_no']}" if podatoci.get("article_no") else ""
        tekst = parche.get("text", "").replace("<", "&lt;").replace(">", "&gt;")
        if potrosheno + len(tekst) > budzet:
            ostanuva = budzet - potrosheno
            if ostanuva < 200:
                break
            tekst = tekst[:ostanuva]
        delovi.append(f'<doc id="{dok_br}" source="{oznaka}{clen}">\n{tekst}\n</doc>')
        potrosheno += len(tekst)
    return "<context>\n" + "\n".join(delovi) + "\n</context>"


def _skrati_istorija(istorija: list[dict]) -> list[dict]:
    skrateni: list[dict] = []
    limit = settings.history_message_chars
    for poraka in istorija:
        tekst = poraka.get("content") or ""
        if len(tekst) > limit:
            tekst = tekst[:limit] + "…"
        skrateni.append({"role": poraka.get("role", "user"), "content": tekst})
    return skrateni


def _build_messages(prashanje: str, parchinja: list[dict], istorija: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_skrati_istorija(istorija),
        {
            "role": "user",
            "content": (
                f"{_build_context(parchinja)}\n\n"
                f"Прашање на студентот: {prashanje}{_lang_directive(prashanje)}"
            ),
        },
    ]

# gpt-oss se "reasoning" modeli: "low" troshi mnogu pomalku tokeni (podolgo traat dnevnite limiti) i e pobrz.
# Za drugi modeli ne se prakja nisto, za da ne frli greska.
def llm_extra() -> dict:
    if "gpt-oss" in settings.llm_model:
        return {"extra_body": {"reasoning_effort": "low"}}
    return {}

#glavna funkcija za cel odgovor odednas, istorija e opcionalno
def generate(prashanje: str, parchinja: list[dict], istorija: list[dict] | None = None) -> str:
    consume_llm()
    resp = get_llm_client().chat.completions.create(   # se povikuva llm ot
        model=settings.llm_model,   # se zima modelot od .env
        messages=_build_messages(prashanje, parchinja, istorija or []), # se gradat porakite, istorija or [] ako e none, korsni prazna lista
        temperature=settings.llm_temperature,   # temperaturata vo env e niska so toa imame pomala halucinacija
        max_tokens=settings.max_answer_tokens,  # max dolzina na odgovorot
        **llm_extra(),                         # reasoning_effort=low za gpt-oss
    )
    return (resp.choices[0].message.content or "").strip()  # se zima sodrzinata, i se iscistat praznite mesta

# funkcija za token po teken , ova e generator
def stream_generate(prashanje: str, parchinja: list[dict],istorija: list[dict] | None = None):
    consume_llm()
    strim = get_llm_client().chat.completions.create(   #istiot povik, no 
        model=settings.llm_model,
        messages=_build_messages(prashanje, parchinja, istorija or []),
        temperature=settings.llm_temperature,
        max_tokens=settings.max_answer_tokens,
        stream=True,    # strema = True llm ot vraka del po del kako sto generira, namesta da se ceka na se
        **llm_extra(),                         # reasoning_effort=low za gpt-oss
    )
    for delce in strim: # pominuva nis sekoe parce od strimot
        delta = delce.choices[0].delta.content if delce.choices else None   # se vadi noviot tekst. Kaj streaming se dava delta samo razlikata i noviot del.
        if delta:   # ako ima nov tekst
            yield delta # se praka vednas, yield go pauzira oba, go dava delceto na povikuvacot i prodolzuva od tuka pri sledno baranje