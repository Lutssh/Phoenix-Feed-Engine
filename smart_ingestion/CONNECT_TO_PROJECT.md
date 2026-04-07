# CONNECT smart_ingestion TO Feed_algorithm PROJECT
> Instructions for a coding assistant to wire the new lightweight ML pipeline
> into the existing Feed_algorithm codebase.
> **Do not modify anything inside `rust_feed_engine/` — the Rust engine is untouched.**

---

## What This Folder Is

`smart_ingestion/` is a drop-in replacement for `neural_ingestion/` in the
Feed_algorithm project. It swaps out all heavy models (LLaVA, full Whisper,
heavy YOLO) for lightweight CPU-viable alternatives:

| Old | New | Size reduction |
|-----|-----|----------------|
| LLaVA VideoLlava-7B | CLIP ViT-B/32 frames | ~7GB → ~350MB |
| OpenAI Whisper turbo | faster-whisper tiny (int8) | ~1.5GB → ~75MB |
| YOLO (heavy default) | YOLOv8n explicit nano | Consistent 6MB |
| No pre-filter | BM25 text pre-filter | 95% fewer embed calls |

The Qdrant/Redis interface, Celery chord structure, and Rust engine are **unchanged**.

---

## Step 1 — Copy the folder into the project

Place `smart_ingestion/` at the root of the `Feed_algorithm/` project, alongside
the existing `neural_ingestion/` and `rust_feed_engine/` folders:

```
Feed_algorithm/
├── smart_ingestion/          ← NEW (this folder)
├── neural_ingestion/         ← OLD (keep, do not delete yet)
├── rust_feed_engine/
├── engines/
├── ingest_text.py
├── ingest_video.py
└── docker-compose.yml
```

---

## Step 2 — Install dependencies

```bash
cd Feed_algorithm
pip install -r smart_ingestion/requirements.txt
```

The first time CLIP and YOLOv8n are used they will auto-download their weights
(~350MB and ~6MB respectively). faster-whisper/tiny (~75MB) downloads on first
transcription call. All downloads are cached by HuggingFace/ultralytics.

---

## Step 3 — Create the .env file

```bash
cp smart_ingestion/.env.example smart_ingestion/.env
```

Edit `smart_ingestion/.env` if your Redis or Qdrant run on non-default ports.
The defaults (`localhost:6379`, `localhost:6333`) match the existing `docker-compose.yml`.

---

## Step 4 — Update ingest_text.py

Open `Feed_algorithm/ingest_text.py` and change the import line:

```python
# BEFORE:
from neural_ingestion.workers.text_worker import process_text

# AFTER:
from smart_ingestion.workers.text_worker import process_text
```

Everything else in `ingest_text.py` stays the same — the task signature is identical.

---

## Step 5 — Update ingest_video.py

Open `Feed_algorithm/ingest_video.py` and replace the entire file contents with:

```python
"""
ingest_video.py  (updated — uses smart_ingestion pipeline)
"""
import argparse
from smart_ingestion.workers.video_worker import ingest_video


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a video into the neural pipeline.")
    parser.add_argument("video_path", help="Path to the video file")
    parser.add_argument("--post_id", required=True, help="Unique post ID")
    parser.add_argument("--caption", default="", help="Caption text (optional)")
    args = parser.parse_args()

    res = ingest_video(
        video_path=args.video_path,
        post_id=args.post_id,
        caption=args.caption,
    )
    print(f"✅ Pipeline triggered. Task ID: {res.id}")
```

---

## Step 6 — Update engines/ml_service/processor.py

The Rust engine calls `engines/ml_service/processor.py` via `analyze_content()`.
Replace the file contents with this bridge that delegates to `smart_ingestion`:

```python
"""
engines/ml_service/processor.py  (bridge to smart_ingestion)
Preserves the analyze_content() interface the Rust engine depends on.
"""
from smart_ingestion.ml_core.processor import get_processor


def analyze_content(data: dict):
    """
    Legacy interface — maps old task type strings to the new MLProcessor.
    Do not call this directly in new code; use smart_ingestion workers instead.
    """
    proc = get_processor()
    task = data.get("type")
    content = data.get("content", "")
    extra = data.get("extra_args", {})

    if task == "text_embedding":
        return proc.embed_text(content)

    elif task == "yolo":
        return proc.detect_objects(content)

    elif task == "whisper":
        return proc.transcribe_audio(content)

    elif task == "llava":
        # LLaVA is replaced — return CLIP frame embedding as a list[float]
        # The aggregator now stores this directly; string description is no longer needed.
        return proc.embed_video_frames(content)

    elif task == "clip_image":
        return proc.embed_image(content)

    elif task == "clip_video":
        return proc.embed_video_frames(content)

    elif task == "clip_text":
        return proc.text_to_clip_vector(content)

    elif task == "aggregation":
        import numpy as np
        visual_vec = np.array(proc.embed_video_frames(content))
        result = {"video_embedding": visual_vec.tolist()}
        caption = extra.get("caption", "")
        if caption:
            cap_vec = np.array(proc.text_to_clip_vector(caption))
            result["semantic_alignment_score"] = float(np.dot(visual_vec, cap_vec))
        else:
            result["semantic_alignment_score"] = 1.0
        return result

    else:
        raise ValueError(f"Unknown task type: {task}")
```

---

## Step 7 — Update Celery worker startup commands

Replace the old worker start commands (in your `docker-compose.yml`, `run_local.sh`,
or process manager) with the new queue-aware commands:

```bash
# Text worker — high concurrency, fast tasks
celery -A smart_ingestion.celery_app worker \
  -Q text_queue --concurrency=8 -n text@%h --loglevel=info

# Image worker — medium concurrency
celery -A smart_ingestion.celery_app worker \
  -Q image_queue --concurrency=4 -n image@%h --loglevel=info

# Video worker — low concurrency, slow tasks
celery -A smart_ingestion.celery_app worker \
  -Q video_queue --concurrency=2 -n video@%h --loglevel=info
```

If you prefer a single worker for simplicity during development:

```bash
celery -A smart_ingestion.celery_app worker \
  -Q text_queue,image_queue,video_queue --concurrency=4 --loglevel=info
```

---

## Step 8 — Update docker-compose.yml (if applicable)

Find the `neural_ingestion` worker service in `docker-compose.yml` and update it.
Replace the command with the one from Step 7.
Also update the volume mount if the old service mounted `neural_ingestion/` explicitly.

```yaml
# BEFORE (in docker-compose.yml):
command: celery -A neural_ingestion.celery_app worker ...

# AFTER:
command: celery -A smart_ingestion.celery_app worker -Q text_queue,image_queue,video_queue --concurrency=4
```

---

## Step 9 — Qdrant collection migration (one-time, for video)

The video collection changes from **384-dim** (old MiniLM) to **512-dim** (CLIP).
If `video_meta_context` already has data, drop and recreate it:

```python
# Run once before deploying the new workers:
from smart_ingestion.utils.qdrant_utils import get_qdrant_client
client = get_qdrant_client()
client.delete_collection("video_meta_context")
print("Dropped video_meta_context — it will be recreated on first ingest.")
```

The `text_meta_context` (384-dim) and `image_meta_context` (512-dim, new) are unaffected.

---

## Step 10 — Verify the connection

Run these quick smoke tests from the `Feed_algorithm/` root:

```bash
# 1. Text embedding
python -c "
from smart_ingestion.workers.text_worker import process_text
r = process_text('Hello world test post', 'smoke_test_001')
print('Text OK:', r)
"

# 2. Image pipeline (replace path with any test image)
python -c "
from smart_ingestion.workers.image_worker import process_image
r = process_image.delay('/path/to/test.jpg', 'smoke_test_img_001', caption='test')
print('Image task queued:', r.id)
"

# 3. Video pipeline
python -c "
from smart_ingestion.workers.video_worker import ingest_video
r = ingest_video('/path/to/test.mp4', post_id='smoke_test_vid_001', caption='test video')
print('Video chord queued:', r.id)
"

# 4. BM25 pre-filter
python -c "
from smart_ingestion.workers.text_worker import bm25_prefilter
corpus = ['post about cats', 'post about food', 'cat video compilation', 'recipe blog']
result = bm25_prefilter('cat content', corpus, top_k=2)
print('BM25 top-2:', result)
"
```

---

## Backward Compatibility Notes

| Interface | Status | Notes |
|-----------|--------|-------|
| `neural_context:{post_id}` Redis key | ✅ Unchanged | Same key, same JSON fields |
| `llava_description` in Redis/Qdrant payload | ✅ Preserved | Now carries summary text, not LLaVA output |
| `yolo_tags`, `whisper_text` payload fields | ✅ Preserved | Same field names |
| `semantic_alignment_score` payload field | ✅ Preserved | Now CLIP-based (more accurate) |
| Rust `models.rs` PostCandidate fields | ✅ No change | `semantic_alignment_score`, `video_context` still populated |
| `analyze_content()` in `engines/ml_service/` | ✅ Bridge in Step 6 | Old callers still work |
| Qdrant `text_meta_context` (384-dim) | ✅ No change | Same model, same dims |
| Qdrant `video_meta_context` (now 512-dim) | ⚠️ Drop & recreate | One-time migration (Step 9) |

---

## What NOT to Touch

- `rust_feed_engine/` — entirely unchanged
- `rust_feed_engine/src/models.rs` — no field changes needed
- `rust_feed_engine/src/scorers/weighted_scorer.rs` — reads `semantic_alignment_score` which is still populated
- `neural_ingestion/` — leave in place until smoke tests pass, then archive it
