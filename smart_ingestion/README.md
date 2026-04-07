# smart_ingestion
**Lightweight neural ingestion pipeline for feed ranking**

A drop-in replacement for `neural_ingestion/` in the Feed_algorithm project.
Every model selected is CPU-viable, fast, and production-battle-tested.

---

## Model Stack

| Modality | Model | Size | Output | Latency (CPU) |
|----------|-------|------|--------|--------------|
| Text embedding | all-MiniLM-L6-v2 | 22 MB | 384-dim | ~14ms |
| Text pre-filter | BM25 (rank_bm25) | 0 MB | ranked list | <1ms |
| Image embedding | CLIP ViT-B/32 | 350 MB | 512-dim | ~150ms |
| Image objects | YOLOv8n | 6 MB | tag list | ~50ms |
| Video frames | CLIP ViT-B/32 (shared) | 350 MB | 512-dim avg | ~800ms (8 frames) |
| Video audio | faster-whisper tiny int8 | 75 MB | transcript | ~200ms |
| Video objects | YOLOv8n (shared) | 6 MB | tag list | ~50ms/frame |

**Total model footprint: ~803MB vs ~9GB+ with LLaVA**
**Peak worker RAM: ~1.2GB vs ~8GB+ with LLaVA**

---

## Key Design Decisions

**CLIP replaces LLaVA** — CLIP produces 512-dim vectors directly (no generative
description step). Image and text embeddings live in the same vector space,
enabling direct cross-modal ANN search and accurate caption-vs-image alignment
scoring without an intermediate language model.

**faster-whisper/tiny replaces OpenAI Whisper/turbo** — CTranslate2-optimised
with int8 quantisation. 4× faster, 70% less RAM. For short social media clips
the accuracy delta is negligible for feed ranking purposes.

**BM25 narrows text candidates before neural embedding** — running MiniLM on
every post in a 10,000-candidate pool is wasteful. BM25 narrows to the top-50
in <1ms. Only the shortlist gets neural-embedded.

**Vector-native pipeline** — the aggregator stores a 512-dim CLIP vector in
Qdrant. The Rust feed engine queries this directly for ANN retrieval without
needing to decode text descriptions.

---

## Folder Structure

```
smart_ingestion/
├── config.py                   Settings (all tunable via env vars)
├── celery_app.py               Celery app + queue routing
├── requirements.txt            Pinned dependencies
├── .env.example                Environment template
├── CONNECT_TO_PROJECT.md       Step-by-step integration guide
├── ml_core/
│   ├── processor.py            MLProcessor — all model logic lives here
│   └── bm25_filter.py          BM25Filter — text pre-filter
├── workers/
│   ├── text_worker.py          process_text + process_text_batch Celery tasks
│   ├── image_worker.py         process_image Celery task
│   ├── video_worker.py         chord entry-point + sub-tasks
│   └── aggregator.py           synthesize_and_index chord callback
└── utils/
    ├── qdrant_utils.py         Qdrant client helpers
    └── redis_utils.py          Redis cache helpers
```

---

## Quick Start (standalone test, no Celery)

```python
from smart_ingestion.ml_core.processor import get_processor

proc = get_processor()

# Text
vec = proc.embed_text("Machine learning for social feeds")
print(f"Text vector: dim={len(vec)}")

# Image
result = proc.process_image("/path/to/image.jpg", caption="sunset photo")
print(f"Image: tags={result['object_tags']}, align={result['alignment_score']:.3f}")

# Video
result = proc.process_video("/path/to/clip.mp4", caption="cooking tutorial")
print(f"Video: transcript={result['transcript'][:80]}")
print(f"       tags={result['object_tags']}, align={result['alignment_score']:.3f}")

# Cross-modal: find which caption best matches an image
img_vec = proc.embed_image("/path/to/image.jpg")
captions = ["a dog playing", "a sunset", "a cooking show"]
for c in captions:
    txt_vec = proc.text_to_clip_vector(c)
    score = proc.vector_similarity(img_vec, txt_vec)
    print(f"  '{c}' → {score:.3f}")
```

---

See **CONNECT_TO_PROJECT.md** for full integration steps.
