"""
utils/qdrant_utils.py
─────────────────────
Qdrant client helpers — collection init, upsert, and ANN search.
Mirrors the interface in the original neural_ingestion/utils/qdrant_utils.py
so the rest of the codebase doesn't need to change.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Collection dimension registry — keeps create/search in sync
COLLECTION_DIMS: Dict[str, int] = {
    "text_meta_context": 384,   # MiniLM-L6-v2
    "image_meta_context": 512,  # CLIP ViT-B/32
    "video_meta_context": 512,  # CLIP ViT-B/32
}


def get_qdrant_client():
    """Return a Qdrant client connected to the configured host/port."""
    from qdrant_client import QdrantClient
    from smart_ingestion.config import settings
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


def init_qdrant_collection(collection_name: str, vector_size: int) -> None:
    """
    Create the collection if it does not exist.
    Uses cosine distance — works correctly because all vectors are L2-normalised
    (cosine similarity == dot product for unit vectors).
    """
    from qdrant_client.models import Distance, VectorParams
    client = get_qdrant_client()

    existing = {c.name for c in client.get_collections().collections}
    if collection_name in existing:
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    logger.info("Created Qdrant collection '%s' (dim=%d)", collection_name, vector_size)


def upsert_point(
    collection_name: str,
    point_id: str,
    vector: List[float],
    payload: Dict[str, Any],
) -> None:
    """Upsert a single point. Creates the collection if needed."""
    from qdrant_client.models import PointStruct
    init_qdrant_collection(collection_name, len(vector))
    client = get_qdrant_client()
    client.upsert(
        collection_name=collection_name,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )


def search_similar(
    collection_name: str,
    query_vector: List[float],
    top_k: int = 20,
    score_threshold: float = 0.0,
    payload_filter: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    ANN search in the given collection.
    Returns a list of {id, score, payload} dicts sorted by score descending.
    """
    client = get_qdrant_client()
    kwargs: Dict[str, Any] = {
        "collection_name": collection_name,
        "query_vector": query_vector,
        "limit": top_k,
        "score_threshold": score_threshold,
        "with_payload": True,
    }
    if payload_filter is not None:
        kwargs["query_filter"] = payload_filter

    hits = client.search(**kwargs)
    return [{"id": h.id, "score": h.score, "payload": h.payload} for h in hits]
