"""
celery_app.py
─────────────
Celery application instance for smart_ingestion workers.

Queue layout
────────────
  text_queue   — fast, high-volume  (~14ms/task)
  image_queue  — medium             (~200-400ms/task)
  video_queue  — slow, rate-limited (~2-5s/task)

Start workers with per-queue concurrency tuned to the task cost:

  celery -A smart_ingestion.celery_app worker -Q text_queue  --concurrency=8 -n text@%h
  celery -A smart_ingestion.celery_app worker -Q image_queue --concurrency=4 -n image@%h
  celery -A smart_ingestion.celery_app worker -Q video_queue --concurrency=2 -n video@%h
"""
from celery import Celery
from smart_ingestion.config import settings

app = Celery(
    "smart_ingestion",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "smart_ingestion.workers.text_worker",
        "smart_ingestion.workers.image_worker",
        "smart_ingestion.workers.video_worker",
        "smart_ingestion.workers.aggregator",
    ],
)

app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Reliability
    task_acks_late=True,           # ack only after task completes
    task_reject_on_worker_lost=True,

    # Performance
    worker_prefetch_multiplier=1,  # prevent one worker hoarding tasks
    task_compression="gzip",       # saves Redis bandwidth for large payloads

    # Routing
    task_routes={
        "smart_ingestion.workers.text_worker.*":  {"queue": "text_queue"},
        "smart_ingestion.workers.image_worker.*": {"queue": "image_queue"},
        "smart_ingestion.workers.video_worker.*": {"queue": "video_queue"},
        "smart_ingestion.workers.aggregator.*":   {"queue": "video_queue"},
    },

    # Result expiry
    result_expires=3600,  # 1 hour
)


from celery.signals import worker_ready


@worker_ready.connect
def warmup_models(sender, **kwargs):
    """Pre-load all models into RAM on worker startup so first tasks aren't slow."""
    import logging
    log = logging.getLogger(__name__)
    log.info("Warming up ML models...")
    from smart_ingestion.ml_core.processor import get_processor
    proc = get_processor()
    proc.embed_text("warmup")           # loads MiniLM
    proc.text_to_clip_vector("warmup")  # loads CLIP text encoder
    
    # Warm image path — requires a dummy image
    import numpy as np
    from PIL import Image
    dummy = Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8))
    proc._clip_image_embed(dummy)       # CLIP vision
    proc._get_yolo()                    # YOLOv8n
    proc._get_whisper()                 # faster-whisper
    
    log.info("All models warm — worker ready.")
