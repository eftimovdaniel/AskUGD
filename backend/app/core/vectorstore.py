"""Qdrant hybrid vektor store: dense (e5) + sparse (BM25), RRF fusion.

Моделите (FastEmbed) се вчитуваат лениво и еднаш по процес.
Сите мрежни операции имаат retry со backoff.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypeVar

from qdrant_client import QdrantClient, models

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
_RETRIES = 3
_BACKOFF = 1.0

# e5 моделите бараат префикси — без нив квалитетот значително паѓа
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "

_client: QdrantClient | None = None
_dense = None
_sparse = None


def _with_retries(fn: Callable[[], T], what: str) -> T:
    posledna: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            return fn()
        except Exception as greshka:  # noqa: BLE001
            posledna = greshka
            if attempt < _RETRIES:
                cekaj = _BACKOFF * (2 ** (attempt - 1))
                logger.warning("%s не успеа (обид %d/%d): %s — повтор за %.1fs",
                               what, attempt, _RETRIES, greshka, cekaj)
                time.sleep(cekaj)
    raise RuntimeError(f"{what} не успеа по {_RETRIES} обиди: {posledna}") from posledna


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url,
                               api_key=settings.qdrant_api_key, timeout=30)
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


# ------------------------------------------------------------------ setup
def ensure_collection() -> None:
    client = get_client()
    ime = settings.qdrant_collection
    if client.collection_exists(ime):
        return
    retka_konfig = None
    if settings.use_hybrid:
        retka_konfig = {"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)}
    client.create_collection(
        collection_name=ime,
        vectors_config={"dense": models.VectorParams(
            size=settings.dense_dim, distance=models.Distance.COSINE)},
        sparse_vectors_config=retka_konfig,
    )
    client.create_payload_index(ime, field_name="source",
                                field_schema=models.PayloadSchemaType.KEYWORD)
    logger.info("Креирана колекција '%s' (hybrid=%s)", ime, settings.use_hybrid)


def ready() -> bool:
    """За /ready проба — дали Qdrant е достапен."""
    try:
        get_client().get_collection(settings.qdrant_collection)
        return True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ write
def upsert_chunks(texts: list[str], metas: list[dict], ids: list[str],
                  batch_size: int = 32) -> None:
    """Ембедирај и запиши парчиња (идемпотентно — исти ID = замена)."""
    if not (len(texts) == len(metas) == len(ids)):
        raise ValueError("texts/metas/ids мора да се со иста должина")
    gust_model = _get_dense()
    redok_model = _get_sparse() if settings.use_hybrid else None

    for pocetok in range(0, len(texts), batch_size):
        tekstovi_serija = texts[pocetok:pocetok + batch_size]
        gusti_vektori = list(gust_model.embed(
            [_PASSAGE_PREFIX + tekst for tekst in tekstovi_serija]))
        retki_vektori = (list(redok_model.embed(tekstovi_serija))
                       if redok_model else [None] * len(tekstovi_serija))

        tocki = []
        for pomest, tekst in enumerate(tekstovi_serija):
            globalen_indeks = pocetok + pomest
            vektor: dict[str, Any] = {"dense": gusti_vektori[pomest].tolist()}
            if retki_vektori[pomest] is not None:
                vektor["bm25"] = models.SparseVector(
                    indices=retki_vektori[pomest].indices.tolist(),
                    values=retki_vektori[pomest].values.tolist(),
                )
            tocki.append(models.PointStruct(
                id=ids[globalen_indeks], vector=vektor,
                payload={"text": tekst, **metas[globalen_indeks]}))

        _with_retries(
            lambda pts=tocki: get_client().upsert(
                collection_name=settings.qdrant_collection, points=pts),
            "Qdrant upsert",
        )


def delete_by_source(source: str) -> None:
    """Избриши ги сите парчиња за даден извор (фајл или URL)."""
    _with_retries(
        lambda: get_client().delete(
            collection_name=settings.qdrant_collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="source",
                                      match=models.MatchValue(value=source)),
            ])),
        ),
        f"Qdrant delete за {source}",
    )


# ------------------------------------------------------------------ search
def search(query: str, limit: int) -> list[dict]:
    """Hybrid (dense + BM25, RRF) или само dense пребарување.

    Враќа [{id, tekst, score, payload}] сортирано по релевантност.
    """
    gust_vektor = list(_get_dense().embed([_QUERY_PREFIX + query]))[0].tolist()

    if settings.use_hybrid:
        retko_baranje = list(_get_sparse().embed([query]))[0]
        rezultat = _with_retries(
            lambda: get_client().query_points(
                collection_name=settings.qdrant_collection,
                prefetch=[
                    models.Prefetch(query=gust_vektor, using="dense", limit=limit * 2),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=retko_baranje.indices.tolist(),
                            values=retko_baranje.values.tolist()),
                        using="bm25", limit=limit * 2),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit, with_payload=True,
            ),
            "Qdrant hybrid search",
        )
    else:
        rezultat = _with_retries(
            lambda: get_client().query_points(
                collection_name=settings.qdrant_collection,
                query=gust_vektor, using="dense", limit=limit, with_payload=True,
            ),
            "Qdrant dense search",
        )

    return [
        {
            "id": str(tocka.id),
            "text": (tocka.payload or {}).get("text", ""),
            "score": tocka.score,
            "payload": tocka.payload or {},
        }
        for tocka in rezultat.points
    ]
