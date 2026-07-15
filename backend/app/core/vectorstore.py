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
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "
_client: QdrantClient | None = None
_dense = None
_sparse = None

def _with_retries (fn: Callable[[], T], what: str) -> T:
    last: Exception | None = None
    for attempt in range (1, _RETRIES +1 ):
        try:
            return fn()
        except Exception as error:
            last = error
            if attempt < _RETRIES:
                wait = _BACKOFF * (2 ** (attempt - 1))
                logger.warning("%s не успеа (обид %d/%d): %s — повтор за %.1fs", what, attempt, _RETRIES, error, wait)
                time.sleep(wait)
    raise RuntimeError (f"{what} не успеа по {_RETRIES} обиди: {last}") from last

def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)
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
        logger.info ("Вчитувам sparse модел %s ...", settings.sparse_model)
        _sparse = SparseTextEmbedding(model_name=settings.sparse_model)
    return _sparse

def ensure_collection() -> None:
    client = get_client()
    name = settings.qdrant_collection
    if client.collection_exist(name):
        return
    sparse_cfg = None
    if settings.use_hybrid:
        sparse_cfg = {"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)}
    client.create_collection(
        collection_name=name,
        vectors_config={"dense": models.VectorParams(
            size=settings.dense_dim, distance=models.Distance.COSINE)},
        sparse_vectors_config=sparse_cfg,
    )
    client.create_payload_index(name, field_name="source", ield_schema=models.PayloadSchemaType.KEYWORD)
    logger.info("Креирана колекција '%s' (hybrid=%s)", name, settings.use_hybrid)

def ready() -> bool:
    try:
        get_client().get_collection(settings.gdrant_collection)
        return True
    except Exception:
        return False
    
def upsert_chunks(texts: list[str], metas: list[dict], ids: list[str], batch_size: int = 32) -> None:
    if not (len(texts) == len(metas) == len(ids)):
        raise ValueError("texts/metas/ids мора да се со иста должина")
    dense_model = _get_dense()
    sparse_model = _get_sparse() if settings.use_hybrid else None

    for start in range (0, len(texts), batch_size):
        batch_texts = texts[start: start + batch_size]
        dense_vecs = list(dense_model.embed([_PASSAGE_PREFIX + text for text in batch_texts]))
        sparse_vecs = (list (sparse_model.embed(batch_texts))
                       if sparse_model else [None] * len(batch_texts))
        points = []
        for offset, text in enumerate (batch_texts):
            global_index = start + offset
            vector : dict[str, Any] = {"dense": dense_vecs[offset].tolist()}
            if sparse_vecs[offset] is not None:
                vector["bm25"] = model.SparseVector( indices=sparse_vecs[offset].indices.tolist(), values = sparse_vecs[offset].values.tolist(),)
            points.append(models.PointStruct( id=ids[global_index], vector=vector, payload={"text": text, **metas[global_index]}))
        _with_retries(
            lambda pts = points: get_client().upsert( collection_name=settings.qdrant_collection, points=pts), "Qdrant upsert", )

def delete_by_source (source: str)-> None:
    _with_retries(
        lambda: get_client().delete(collection_name=settings.qdrant_collection,
                                    points_selector=models.FilterSelector(filter=models.Filter(must=[
                                        models.FieldCondition(key="source",match=models.MatchValue(value=source)),])),)
    )

def search (query: str, limit: int) -> list[dict]:
    dense_vec = list(_get_dense().embed([_QUERY_PREFIX + query]))[0].tolist()
    if settings.use_hybrid:
        sparse_query = list(_get_sparse().embed([query]))[0]
        result = _with_retries(
            lambda: get_client().query_points(
                collction_name = settings.qdrant_collection,
                prefetch=[
                    models.Prefetch(query=dense_vec, using="dense", limit=limit * 2),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_query.indices.tolist(),
                            values=sparse_query.values.tolist()),
                        using="bm25", limit=limit * 2),
                ],
                query = models.FusionQuery(fusion=models.Fusion.RRF),limit = limit, with_payload = True,
            ), "Qdrant hybrid search",
        )
    else:
        result = _with_retries(
            lambda: get_client().query_points(
                collection_name = settings.qdrant_collection,
                query = dense_vec, using = "dense", limit = limit, with_payload = True,
            ), "Qdrant dense search",)
    
    return [
        {
            "id": str(point.id),
            "text": (point.payload or {}).get("text", ""),
            "score": point.score,
            "payload": point.payload or {},
        }
        for point in result.points
        ] 


            
