"""
workers/image_worker.py
────────────────────────
Celery task: process and index an image post.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from smart_ingestion.celery_app import app
from smart_ingestion.config import settings
from smart_ingestion.ml_core.processor import get_processor
from smart_ingestion.utils.qdrant_utils import upsert_point
from smart_ingestion.utils.redis_utils import cache_neural_context

from smart_ingestion.utils.media_utils import validate_media_path

logger = logging.getLogger(__name__)


@app.task(
    name="smart_ingestion.workers.image_worker.process_image",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_image(
    self,
    image_path: str,
    post_id: str,
    caption: str = "",
    metadata: Optional[Dict] = None,
) -> Dict:
    try:
        image_path = validate_media_path(image_path)
        proc = get_processor()
        result = proc.process_image(image_path, caption=caption)

        embedding = result["embedding"]
        tags = result["object_tags"]
        alignment = result["alignment_score"]

        payload = {
            "image_path": image_path,
            "post_id": post_id,
            "type": "image",
            "object_tags": tags,
            "caption": caption,
            "alignment_score": alignment,
            "created_at_ms": int(time.time() * 1000),
            "semantic_alignment_score": alignment,
        }
        if metadata:
            payload.update(metadata)

        upsert_point(
            collection_name=settings.IMAGE_COLLECTION,
            point_id=int(post_id),
            vector=embedding,
            payload=payload,
        )

        cache_neural_context(post_id, {
            "type": "image",
            "embedding": embedding,
            "object_tags": tags,
            "alignment_score": alignment,
            "caption": caption,
            "semantic_alignment_score": alignment,
        })

        logger.info("image indexed | post=%s | tags=%s | align=%.3f",
                    post_id, tags, alignment)

        return {
            "status": "indexed",
            "post_id": post_id,
            "dim": len(embedding),
            "object_tags": tags,
            "alignment_score": alignment,
        }

    except Exception as exc:
        logger.exception("process_image failed for post %s", post_id)
        if self:
            raise self.retry(exc=exc)
        raise exc


@app.task(
    name="smart_ingestion.workers.image_worker.get_image_embedding",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def get_image_embedding(self, image_path: str) -> Dict:
    try:
        image_path = validate_media_path(image_path)
        proc = get_processor()
        result = proc.process_image(image_path)
        return {
            "embedding": result["embedding"],
            "object_tags": result["object_tags"],
        }
    except Exception as exc:
        raise self.retry(exc=exc)
