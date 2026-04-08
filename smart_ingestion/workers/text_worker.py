"""
workers/text_worker.py
───────────────────────
Celery task: process and index a text post.

Pipeline
────────
  1. BM25 pre-filter  — optional, used when a reference corpus is provided
  2. MiniLM-L6-v2    — 384-dim embedding
  3. Qdrant upsert   — collection: text_meta_context
  4. Redis cache     — key: neural_context:{post_id}

Drop-in replacement for neural_ingestion/workers/text_worker.py.
Task name is preserved for compatibility with existing .delay() callers.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from smart_ingestion.celery_app import app
from smart_ingestion.config import settings
from smart_ingestion.ml_core.processor import get_processor
from smart_ingestion.utils.qdrant_utils import upsert_point
from smart_ingestion.utils.redis_utils import cache_neural_context

logger = logging.getLogger(__name__)


@app.task(
    name="smart_ingestion.workers.text_worker.process_text",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def process_text(
    self,
    text: str,
    post_id: str,
    metadata: Optional[Dict] = None,
) -> Dict:
    """
    Embed a text post and index it in Qdrant.

    Parameters
    ----------
    text     : Raw post text.
    post_id  : Unique post identifier (used as cache key and payload field).
    metadata : Optional extra fields merged into the Qdrant payload.

    Returns
    -------
    {"status": "indexed", "post_id": ..., "dim": 384}
    """
    try:
        proc = get_processor()
        embedding = proc.embed_text(text)

        payload = {
            "text": text,
            "post_id": post_id,
            "type": "text_only",
            "created_at_ms": int(time.time() * 1000),
        }
        if metadata:
            payload.update(metadata)

        # Qdrant
        upsert_point(
            collection_name=settings.TEXT_COLLECTION,
            point_id=int(post_id),
            vector=embedding,
            payload=payload,
        )

        # Redis
        cache_neural_context(post_id, {
            "embedding": embedding,
            "type": "text",
            "payload": payload,
        })

        return {"status": "indexed", "post_id": post_id, "dim": len(embedding)}

    except Exception as exc:
        logger.exception("process_text failed for post %s", post_id)
        raise self.retry(exc=exc)


@app.task(
    name="smart_ingestion.workers.text_worker.process_text_batch",
    bind=True,
    max_retries=2,
)
def process_text_batch(
    self,
    items: List[Dict],
) -> Dict:
    """
    Batch ingest multiple text posts in one task — more efficient than
    firing N individual process_text tasks when ingesting bulk content.

    Parameters
    ----------
    items : List of {"text": str, "post_id": str, "metadata": dict | None}

    Returns
    -------
    {"status": "indexed", "count": N}
    """
    try:
        proc = get_processor()

        texts = [it["text"] for it in items]
        embeddings = proc.embed_texts_batch(texts)

        for item, embedding in zip(items, embeddings):
            post_id = item["post_id"]
            meta = item.get("metadata") or {}
            payload = {
                "text": item["text"],
                "post_id": post_id,
                "type": "text_only",
                "created_at_ms": int(time.time() * 1000),
                **meta
            }

            upsert_point(
                collection_name=settings.TEXT_COLLECTION,
                point_id=int(post_id),
                vector=embedding,
                payload=payload,
            )
            cache_neural_context(post_id, {"embedding": embedding, "type": "text"})

        return {"status": "indexed", "count": len(items)}

    except Exception as exc:
        logger.exception("process_text_batch failed")
        raise self.retry(exc=exc)


def bm25_prefilter(
    query_text: str,
    candidate_texts: List[str],
    top_k: Optional[int] = None,
) -> List[str]:
    """
    Utility function (NOT a Celery task) — narrow a candidate pool with BM25
    before sending the winners to process_text or process_text_batch.

    Call this in your post retrieval layer, not inside the worker itself.

    Example
    -------
        shortlist = bm25_prefilter(user_interests, all_candidate_texts, top_k=50)
        process_text_batch.delay([{"text": t, "post_id": ...} for t in shortlist])
    """
    from smart_ingestion.ml_core.bm25_filter import BM25Filter
    k = top_k or settings.BM25_TOP_K
    f = BM25Filter(corpus=candidate_texts)
    return f.top_k(query=query_text, k=k)
