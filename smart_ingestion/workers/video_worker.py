"""
workers/video_worker.py
────────────────────────
Celery tasks for video ingestion. Uses a Celery chord (parallel fan-out)
to run the three lightweight sub-pipelines concurrently, then aggregates.

Chord Structure
───────────────
  ┌─ clip_frames_task(video_path)   → 512-dim visual vector
  ├─ transcribe_task(video_path)    → transcript string
  └─ detect_objects_task(video_path)→ list of object tags
                   ↓ chord callback
        aggregator.synthesize_and_index(results, video_path, caption, metadata)

This replaces the old yolo_worker + whisper_worker + llava_worker trio.
Task names use the old scheme where needed for backward compat.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from celery import chord

from smart_ingestion.celery_app import app
from smart_ingestion.ml_core.processor import get_processor
from smart_ingestion.utils.media_utils import validate_media_path

logger = logging.getLogger(__name__)


# ── Sub-tasks (chord headers) ─────────────────────────────────────────────────

@app.task(
    name="smart_ingestion.workers.video_worker.clip_frames_task",
    bind=True,
    max_retries=2,
)
def clip_frames_task(self, video_path: str) -> List[float]:
    """
    Sample VIDEO_FRAME_SAMPLES frames, embed each with CLIP ViT-B/32,
    return the L2-normalised average — the video's visual fingerprint.
    ~800ms for 8 frames on CPU.
    """
    try:
        video_path = validate_media_path(video_path)
        return get_processor().embed_video_frames(video_path)
    except Exception as exc:
        logger.exception("clip_frames_task failed: %s", video_path)
        raise self.retry(exc=exc)


@app.task(
    # Keep old task name so existing callers don't break
    name="smart_ingestion.workers.whisper_worker.process_video",
    bind=True,
    max_retries=2,
)
def transcribe_task(self, video_path: str) -> str:
    """
    faster-whisper (tiny, int8) audio transcription.
    ~4× faster than OpenAI Whisper. ~150-400ms for short clips on CPU.
    """
    try:
        video_path = validate_media_path(video_path)
        return get_processor().transcribe_audio(video_path)
    except Exception as exc:
        logger.exception("transcribe_task failed: %s", video_path)
        raise self.retry(exc=exc)


@app.task(
    # Keep old task name for compatibility
    name="smart_ingestion.workers.yolo_worker.process_video",
    bind=True,
    max_retries=2,
)
def detect_objects_task(self, video_path: str) -> List[str]:
    """
    YOLOv8n object detection across sampled video frames.
    ~30-80ms per sampled frame on CPU.
    """
    try:
        video_path = validate_media_path(video_path)
        return get_processor().detect_objects_video(video_path)
    except Exception as exc:
        logger.exception("detect_objects_task failed: %s", video_path)
        raise self.retry(exc=exc)


# ── Chord entry-point ─────────────────────────────────────────────────────────

def ingest_video(
    video_path: str,
    post_id: str,
    caption: str = "",
    metadata: Optional[Dict] = None,
):
    """
    Kick off the full video ingestion chord.
    Call this instead of the old ingest_video.py script.

    Usage
    -----
        from smart_ingestion.workers.video_worker import ingest_video
        result = ingest_video("/data/videos/abc.mp4", post_id="post_123", caption="...")
    """
    from smart_ingestion.workers.aggregator import synthesize_and_index

    if metadata is None:
        metadata = {}
    metadata["post_id"] = post_id
    if caption:
        metadata["caption"] = caption

    pipeline = chord(
        header=[
            clip_frames_task.s(video_path),
            transcribe_task.s(video_path),
            detect_objects_task.s(video_path),
        ],
        body=synthesize_and_index.s(video_path, metadata),
    )
    return pipeline()
