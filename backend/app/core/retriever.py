from __future__ import annotations
from qdrant_client import QdrantClient
from app.config import settings
from app.core.embeddings import embed_text

__all__ = ["get_client", "retrieve", "embed_text"]

def get_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def retrieve(queries: list[str], top_k: int | None = None) -> list[str]:
    client = get_client()
    k = top_k or settings.top_k

    seen: set[str] = set()
    results: list[str] = []
    for q in queries:
        vector = embed_text(q)
        hits = client.search(
            collection_name=settings.qdrant_collection,
            query_vector=vector,
            limit=k,
        )
        for hit in hits:
            text = (hit.payload or {}).get("text")
            if text and text not in seen:
                seen.add(text)
                results.append(text)
    return results