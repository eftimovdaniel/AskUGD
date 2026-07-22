from __future__ import annotations
import logging
import time
from typing import Any, Callable, TypeVar
from qdrant_client import QdrantClient, models
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T") # promenliva, vraka isti tip kako funkcija
_RETRIES = 3   # max 3 obidi pri mrezna greska 
_BACKOFF = 1.0  # osnova za pauza (1s 2s 3s)

_QUERY_PREFIX = "query: "   #prefiks za prasanje
_PASSAGE_PREFIX = "passage: "   # prefiks za dokumenti
_client: QdrantClient | None = None  #globalen klient, edna vrska za cela aplikacija
_dense = None   #globalen dense model
_sparse = None  # globlen sparse model

def _with_retries(fn: Callable[[], T], what: str) -> T: # povtorliva funkcija pri greksa,
    posledna: Exception | None = None   #ja pamenti poslednata poraka za greksa pri preiranje na finalna poraka
    for attempt in range(1, _RETRIES + 1):  # broi obidi
        try:
            return fn() #uspehot go vraka samo ednas
        except Exception as greshka:  
            posledna = greshka  # vo posledna smestuvame ja greskata koja se javuva
            if attempt < _RETRIES: # dokolkj ne e posleden obid
                cekaj = _BACKOFF * (2 ** (attempt - 1)) # pravime pazuca od 1 2 4s ako servcerot e zafaten cekame podolgo
                logger.warning("%s не успеа (обид %d/%d): %s — повтор за %.1fs", what, attempt, _RETRIES, greshka, cekaj)
                time.sleep(cekaj) # pauziranje pri sleden obid
    raise RuntimeError(f"{what} не успеа по {_RETRIES} обиди: {posledna}") from posledna    # dokolku ne se dobie niso imame samo pad se frla greksa 

def get_client() -> QdrantClient: #dava gdrant klientot
    global _client
    if _client is None: # dokolku nemame vrska so klineto 
        _client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)    # ostvaruvame vrska so istiot
    return _client

def _get_dense():
    global _dense
    if _dense is None:
        from fastembed import TextEmbedding
        logger.info("Вчитувам dense модел %s ...", settings.dense_model)
        _dense = TextEmbedding(model_name=settings.dense_model)
    return _dense

def _get_sparse():
    global _sparse
    if _sparse is None:
        from fastembed import SparseTextEmbedding
        logger.info("Вчитувам sparse модел %s ...", settings.sparse_model)
        _sparse = SparseTextEmbedding(model_name=settings.sparse_model)
    return _sparse

def ensure_collection() -> None:  # sozdavanje kolekcija dokolku ne postoi, ne e pronajdena 
    client = get_client()   
    ime = settings.qdrant_collection    #ime (askugd)
    if client.collection_exists(ime):   # dokolku veke postoi 
        return  # ne vraka nisto
    retka_konfig = None # sparse konfiguracija
    if settings.use_hybrid: # ako e hibrid
        retka_konfig = {"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)}    # se definira bm25 so idf
    client.create_collection( # sozdavanje na kolekcijata
        collection_name=ime,
        vectors_config={"dense": models.VectorParams(   #dense vektor
            size=settings.dense_dim, distance=models.Distance.COSINE)},
        sparse_vectors_config=retka_konfig,
    )
    client.create_payload_index(ime, field_name="source", field_schema=models.PayloadSchemaType.KEYWORD)    # indeks za source za brzo delete by source
    logger.info("Креирана колекција '%s' (hybrid=%s)", ime, settings.use_hybrid)

def ready() -> bool:    # proverka dali bazata e dostapna 
    try:    
        get_client().get_collection(settings.qdrant_collection) #obid da ja zememe kolekcijata 
        return True # ako e zemana dava true 
    except Exception: 
        return False    #dokolku ne e vraka false 

def upsert_chunks(texts: list[str], metas: list[dict], ids: list[str], batch_size: int = 32) -> None:   #embeding i zapisuvanje so batch_size od 32
    if not (len(texts) == len(metas) == len(ids)): #site tri listi mora da se so ista dolzina
        raise ValueError("texts/metas/ids мора да се со иста должина")
    gust_model = _get_dense()   # dense model
    redok_model = _get_sparse() if settings.use_hybrid else None    # sparse samo ako hybrid
    for pocetok in range(0, len(texts), batch_size): # vo serii od 32
        tekstovi_serija = texts[pocetok:pocetok + batch_size]   # tekovna serija
        gusti_vektori = list(gust_model.embed(  # embeding (tekst vo vektor)
            [_PASSAGE_PREFIX + tekst for tekst in tekstovi_serija]))    # definiran e so passsage prefiks
        retki_vektori = (list(redok_model.embed(tekstovi_serija))   #sparse vektor 
                       if redok_model else [None] * len(tekstovi_serija))   #ili none ako ne e hybrid

        tocki = []  #prazna lista vo koja se sobiraat site points vo serijata za da gi vrati odednas vo qdrant
        for pomest, tekst in enumerate(tekstovi_serija):    # pominuva nis sekoj tekst vo serijata, pomest e pozicijata vo serijata (0, 1, 2 ), tekst e tekstot i enumerate gi dava dvete zaedno
            globalen_indeks = pocetok + pomest # go presmetuka indeksto vo celata lista
            vektor: dict[str, Any] = {"dense": gusti_vektori[pomest].tolist()} #recnik so vektorite na parceto. gusti_vektori[pomest] e numpy so golemina od 1024 bajta, a so tolista se pretvara vo python lista, qdrant ne razbira numpy
            if retki_vektori[pomest] is not None: #proverka dali ima sparse za ova parce, ako sme vo hybrid rezim retki_vektori se none se preskoknuvaat i parceto ima smao dense
                vektor["bm25"] = models.SparseVector(   # dokolku go ima se dodava vo sparse vektorot so kluc bm25
                    indices=retki_vektori[pomest].indices.tolist(), # indices = koi zborovi se prisutni
                    values=retki_vektori[pomest].values.tolist(),   #values = kolki e vazen sekoj od tie zborovi
                )
            tocki.append(models.PointStruct( #sozdavanje na tockata i dodavanje vo listata
                id=ids[globalen_indeks], vector=vektor, # se dodava id na sekoe indektifikuvano/ pronajdeno prace
                payload={"text": tekst, **metas[globalen_indeks]})) # payload = seto pridruzeno sto sakame da go videme, procitame, text go ima tekstot a metas[g_i] gi raspakuva sote polinja

        _with_retries(  # ja praka celata serija tocki vo qdrant
            lambda pts=tocki: get_client().upsert(  #funkcijata koja se izvrasuva, dokolku tockata so toj id veke postoi se zamenuva ako ja nema se vmetnuva
                collection_name=settings.qdrant_collection, points=pts),    # vo koja kolekcija i koi tocki 
            "Qdrant upsert",    # imeto sto se pojavuva vo logovite ako nekoj obid padne
        )

def delete_by_source(source: str) -> None: #gi brise site parcinja sto dosle od eden izvor, se koriste pri povtorno povtoruvanje na ingestion = nema duplikate, samo novi parcinja 
    _with_retries(  
        lambda: get_client().delete(    #se pivikuva funkcijata za brisenje
            collection_name=settings.qdrant_collection, # definirame od koja kolekcija ke se naprave brisenjeto
            points_selector=models.FilterSelector(filter=models.Filter(must=[   #filter so must mora da se ispolni
                models.FieldCondition(key="source",  # uclov bez edno pole od payload, so poleto source
                                      match=models.MatchValue(value=source)), # mora da e tocno ednakvo na dadenoto source
            ])),
        ),
        f"Qdrant delete за {source}",  #ime za logovite
    )

def search(query: str, limit: int) -> list[dict]:   # glavna funkcija za prebaruvanje, se povikuva sekogas koga prasanjeto e postaveno od studentot
    gust_vektor = list(_get_dense().embed([_QUERY_PREFIX + query]))[0].tolist() # prasanjeto se pretvara vo vektor, 
    if settings.use_hybrid: # dokolku koristeme hybrid rezim
        retko_baranje = list(_get_sparse().embed([query]))[0]   #pretvarame go prasanjeto i vo sparse vektor, bez prefiks
        rezultat = _with_retries(   # se vrse prebaruvanjeto
            lambda: get_client().query_points(    # query_points = Qdrant api za hybrid prebaruvanje
                collection_name=settings.qdrant_collection, # se definira kolkekcijata
                prefetch=[  #qdrant pravi dve prebaruvanje i sobira kandidati od sekoe prebaruvanje
                    models.Prefetch(query=gust_vektor, using="dense", limit=limit * 2), #se koriste dense vektoror vrz dense poleto, a so limit*2 zema dvojno poveke kandidati za da imame dvojno poveke matrijali za spojuvanje
                    models.Prefetch( #klucni zborovi
                        query=models.SparseVector(  #sostavi go spatse vektorot na prasanjeto
                            indices=retko_baranje.indices.tolist(), # koi zborovi
                            values=retko_baranje.values.tolist()),  # nivnata tezina
                        using="bm25", limit=limit * 2), # koristi go brz bm25 poletom kaj dvojno kandidati
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF), #RRF spojuva sve listi vo edna finalna, praceto so koj e vo rang vo sekoja lista go zema i go stava na vrvot
                limit=limit, with_payload=True, # so limit kolku finalni rezlutati da vrati, a so with_payload ja vraka metadatata ne samo id ili ocena
            ),
            "Qdrant hybrid search", # ime za logot 
        )
    else:   # dokolku ne sme vo hybrid rezim 
        rezultat = _with_retries(   
            lambda: get_client().query_points(
                collection_name=settings.qdrant_collection,
                query=gust_vektor, using="dense", limit=limit, with_payload=True,   # se samo samo dense vektorot , vrz dense poleto i kolkav e relutatot, so metadata
            ),
            "Qdrant dense search",  # logovi
        )

    return [    # pretvaranje na Qdrant erzultatot vo Python recenica.
        {
            "id": str(tocka.id),   #idetifikuvanje na tockata kako string
            "text": (tocka.payload or {}).get("text", ""),  # se zema samiot tekst na parceto od payload 
            "score": tocka.score,   # ocenkata za releventnosta na parceto 
            "payload": tocka.payload or {}, # celata metadata za izvlekuvanje i gradenje na kontekst
        }
        for tocka in rezultat.points    # za sekoja pronajdena tocka vo rezlutatot
    ]
