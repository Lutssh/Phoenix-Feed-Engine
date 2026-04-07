import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Infrastructure ────────────────────────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", 6333))

    # ── Text ──────────────────────────────────────────────────────────────────
    # all-MiniLM-L6-v2: 22MB, 384-dim, ~14ms/sentence on CPU
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    # BM25 relevance threshold — candidates below this skip neural embedding
    BM25_THRESHOLD: float = 0.3
    # Top-K candidates BM25 keeps before neural re-ranking
    BM25_TOP_K: int = 50

    # ── Image ─────────────────────────────────────────────────────────────────
    # CLIP ViT-B/32: 350MB, 512-dim, ~100-200ms on CPU per image
    CLIP_MODEL: str = "openai/clip-vit-base-patch32"
    # YOLOv8 nano: ~6MB, fastest YOLO variant for object tags
    YOLO_MODEL: str = "yolov8n.pt"

    # ── Video ─────────────────────────────────────────────────────────────────
    # faster-whisper tiny: ~75MB, int8-quantized, ~4x faster than OpenAI Whisper
    WHISPER_MODEL_SIZE: str = "tiny"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"   # int8 = fastest CPU mode
    WHISPER_BEAM_SIZE: int = 1           # greedy decode — fastest, good enough
    # Number of frames sampled per video for CLIP visual fingerprint
    VIDEO_FRAME_SAMPLES: int = 8
    # Max video duration (seconds) processed — longer videos are clipped
    VIDEO_MAX_DURATION_SEC: int = 120

    # ── Qdrant Collections ────────────────────────────────────────────────────
    TEXT_COLLECTION: str = "text_meta_context"    # 384-dim  (MiniLM)
    VIDEO_COLLECTION: str = "video_meta_context"  # 512-dim  (CLIP)
    IMAGE_COLLECTION: str = "image_meta_context"  # 512-dim  (CLIP)

    # ── Cache TTL ─────────────────────────────────────────────────────────────
    CACHE_TTL_SECONDS: int = 86400  # 24 hours

    class Config:
        env_file = ".env"


settings = Settings()
