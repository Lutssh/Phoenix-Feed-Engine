"""
workers/aggregator.py
──────────────────────
Chord callback: receives results from clip_frames_task, transcribe_task,
and detect_objects_task, then synthesizes and indexes the final vector.

Result layout from chord
────────────────────────
  results[0] → list[float]  — 512-dim CLIP visual fingerprint (clip_frames_task)
  results[1] → str          — Whisper transcript              (transcribe_task)
  results[2] → list[str]    — YOLO object tags                (detect_objects_task)

Final storage
─────────────
  Qdrant: video_meta_context  (512-dim CLIP vector)
  Redis:  neural_context:{post_id}
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

import numpy as np

from smart_ingestion.celery_app import app
from smart_ingestion.config import settings
from smart_ingestion.ml_core.processor import get_processor
from smart_ingestion.utils.qdrant_utils import upsert_point
from smart_ingestion.utils.redis_utils import cache_neural_context

logger = logging.getLogger(__name__)


@app.task(
    name="smart_ingestion.workers.aggregator.synthesize_and_index",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def synthesize_and_index(
    self,
    results: List[Any],
    video_path: str,
    metadata: Optional[Dict] = None,
) -> Dict:
    """
    Aggregate the three chord results into a single Qdrant point.

    Parameters
    ----------
    results   : [clip_vector, transcript, object_tags] from the chord.
    video_path: Path to the original video file.
    metadata  : Dict containing at minimum {"post_id": str}.
                May also contain {"caption": str} for alignment scoring.
    """
    try:
        clip_vector, transcript, object_tags = results
        meta = metadata or {}
        post_id = meta.get("post_id", video_path)
        caption = meta.get("caption", "")

        proc = get_processor()

        # ── Visual vector (primary — 512-dim CLIP) ────────────────────────
        visual_vec = np.array(clip_vector, dtype=np.float32)
        norm = np.linalg.norm(visual_vec)
        if norm > 0:
            visual_vec = visual_vec / norm

        # ── Semantic alignment score (CLIP space — text vs visual) ────────
        alignment_score = 1.0
        if caption and norm > 0:
            caption_clip_vec = np.array(
                proc.text_to_clip_vector(caption), dtype=np.float32
            )
            alignment_score = float(np.dot(visual_vec, caption_clip_vec))
            alignment_score = float(np.clip(alignment_score, -1.0, 1.0))

        # ── Transcript embedding (384-dim MiniLM — stored in payload) ─────
        has_transcript = transcript and not transcript.startswith("[")
        transcript_vec = (
            proc.embed_text(transcript) if has_transcript else [0.0] * 384
        )

        # ── Summary text (human-readable for payload / debug) ─────────────
        tags_str = ", ".join(object_tags) if object_tags else "none"
        summary_text = f"Objects: {tags_str}. Audio: {transcript}"

        # ── Qdrant upsert ─────────────────────────────────────────────────
        final_vector = visual_vec.tolist()
        payload: Dict[str, Any] = {
            "video_path": video_path,
            "post_id": post_id,
            "type": "video",
            "object_tags": object_tags,
            "transcript": transcript,
            # transcript_vector stored separately — dim mismatch with video collection
            "summary_text": summary_text,
            "caption": caption,
            "alignment_score": alignment_score,
            # Legacy key — kept so existing Rust hydrators don't break
            "llava_description": summary_text,
        }
        # Merge extra metadata (exclude known keys to avoid duplication)
        skip = {"post_id", "caption"}
        for k, v in meta.items():
            if k not in skip:
                payload[k] = v

        point_id = post_id
        upsert_point(
            collection_name=settings.VIDEO_COLLECTION,
            point_id=point_id,
            vector=final_vector,
            payload=payload,
        )

        # ── Redis cache ───────────────────────────────────────────────────
        cache_neural_context(post_id, {
            "type": "video",
            "alignment_score": alignment_score,
            "object_tags": object_tags,
            "transcript": transcript,
            # Keep legacy key for the Rust engine's hydrator
            "llava_description": summary_text,
            "yolo_tags": object_tags,
            "whisper_text": transcript,
            "semantic_alignment_score": alignment_score,
        })

        logger.info(
            "video indexed | post=%s | tags=%d | align=%.3f | transcript_len=%d",
            post_id, len(object_tags), alignment_score, len(transcript),
        )

        return {
            "point_id": point_id,
            "status": "indexed",
            "post_id": post_id,
            "alignment_score": alignment_score,
            "object_tags": object_tags,
            "transcript_preview": transcript[:120],
        }

    except Exception as exc:
        logger.exception("synthesize_and_index failed for %s", video_path)
        raise self.retry(exc=exc)
