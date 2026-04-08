"""
ml_core/processor.py
─────────────────────
Central ML processor. All models are lazy-loaded on first use so the worker
process starts in <1 second even with no GPU present.

Architecture
────────────
  Text path   →  BM25 pre-filter  →  MiniLM-L6-v2 embed  →  384-dim vector
  Image path  →  YOLOv8n tags     →  CLIP ViT-B/32 embed  →  512-dim vector
  Video path  →  faster-whisper   →  CLIP frame avg embed  →  512-dim vector
                 YOLOv8n tags         MiniLM transcript embed (for payload)
                                      CLIP caption align score

All vectors are L2-normalised before returning so cosine similarity = dot product.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MLProcessor
# ─────────────────────────────────────────────────────────────────────────────

class MLProcessor:
    """
    Singleton-friendly ML model host.
    Instantiate once per worker process and reuse across tasks.
    """

    def __init__(self) -> None:
        # Lazy model handles — populated on first use
        self._embedder = None            # SentenceTransformer (MiniLM)
        self._clip_model = None          # CLIPModel
        self._clip_processor = None      # CLIPProcessor
        self._yolo_model = None          # YOLO (ultralytics)
        self._whisper_model = None       # faster_whisper.WhisperModel
        self._settings = None

    # ── Settings ──────────────────────────────────────────────────────────────

    def _cfg(self):
        if self._settings is None:
            from smart_ingestion.config import settings
            self._settings = settings
        return self._settings

    # ── Lazy loaders ──────────────────────────────────────────────────────────

    def _get_embedder(self):
        if self._embedder is None:
            t0 = time.perf_counter()
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(self._cfg().EMBEDDING_MODEL)
            logger.info("MiniLM loaded in %.2fs", time.perf_counter() - t0)
        return self._embedder

    def _get_clip(self) -> Tuple[Any, Any]:
        if self._clip_model is None:
            t0 = time.perf_counter()
            import torch
            from transformers import CLIPModel, CLIPProcessor
            name = self._cfg().CLIP_MODEL
            self._clip_processor = CLIPProcessor.from_pretrained(name)
            self._clip_model = CLIPModel.from_pretrained(name)
            self._clip_model.eval()
            logger.info("CLIP loaded in %.2fs", time.perf_counter() - t0)
        return self._clip_model, self._clip_processor

    def _get_yolo(self):
        if self._yolo_model is None:
            t0 = time.perf_counter()
            import torch
            from ultralytics import YOLO
            
            # Patch YOLO to handle PyTorch 2.6+ weights_only issue
            original_torch_load = torch.load
            def patched_torch_load(*args, **kwargs):
                if 'weights_only' not in kwargs:
                    kwargs['weights_only'] = False
                return original_torch_load(*args, **kwargs)
            
            torch.load = patched_torch_load
            try:
                self._yolo_model = YOLO(self._cfg().YOLO_MODEL)
            finally:
                torch.load = original_torch_load
                
            logger.info("YOLOv8n loaded in %.2fs", time.perf_counter() - t0)
        return self._yolo_model

    def _get_whisper(self):
        if self._whisper_model is None:
            t0 = time.perf_counter()
            from faster_whisper import WhisperModel
            cfg = self._cfg()
            self._whisper_model = WhisperModel(
                cfg.WHISPER_MODEL_SIZE,
                device=cfg.WHISPER_DEVICE,
                compute_type=cfg.WHISPER_COMPUTE_TYPE,
            )
            logger.info("faster-whisper/%s loaded in %.2fs",
                        cfg.WHISPER_MODEL_SIZE, time.perf_counter() - t0)
        return self._whisper_model

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _l2(vec: np.ndarray) -> np.ndarray:
        """L2-normalise so cosine similarity = dot product."""
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def _clip_image_embed(self, image) -> np.ndarray:
        """
        Embed a PIL Image with CLIP.
        Returns a normalised 512-dim float32 numpy array.
        """
        import torch
        model, proc = self._get_clip()
        inputs = proc(images=image, return_tensors="pt")
        with torch.no_grad():
            feat = model.get_image_features(**inputs)
        return self._l2(feat.squeeze(0).numpy().astype(np.float32))

    def _clip_text_embed(self, text: str) -> np.ndarray:
        """
        Embed a text string with CLIP's text encoder.
        Returns a normalised 512-dim float32 numpy array.
        Lives in the SAME vector space as _clip_image_embed.
        """
        import torch
        model, proc = self._get_clip()
        inputs = proc(
            text=[text], return_tensors="pt",
            padding=True, truncation=True, max_length=77,
        )
        with torch.no_grad():
            feat = model.get_text_features(**inputs)
        return self._l2(feat.squeeze(0).numpy().astype(np.float32))

    # ── ① TEXT ────────────────────────────────────────────────────────────────

    def embed_text(self, text: str) -> List[float]:
        """
        MiniLM-L6-v2 text embedding.
        Returns a normalised 384-dim float list ready for Qdrant.
        ~14ms on CPU.
        """
        embedder = self._get_embedder()
        vec = embedder.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_texts_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """
        Batch encode multiple texts — faster than calling embed_text() in a loop.
        """
        embedder = self._get_embedder()
        vecs = embedder.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vecs.tolist()

    def text_similarity(self, text_a: str, text_b: str) -> float:
        """Cosine similarity between two texts. Result in [-1, 1]."""
        va = np.array(self.embed_text(text_a))
        vb = np.array(self.embed_text(text_b))
        return float(np.dot(va, vb))  # already L2-normalised

    # ── ② IMAGE ───────────────────────────────────────────────────────────────

    def embed_image(self, image_path: str) -> List[float]:
        """
        CLIP image embedding.
        Returns a normalised 512-dim float list.
        ~100-200ms on CPU.
        """
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        return self._clip_image_embed(img).tolist()

    def detect_objects(self, image_path: str) -> List[str]:
        """
        YOLOv8n object detection for an image.
        Returns a deduplicated list of object class labels found.
        ~30-80ms on CPU.
        """
        model = self._get_yolo()
        results = model(image_path, verbose=False)
        labels: set[str] = set()
        for r in results:
            for box in r.boxes:
                cls = int(box.cls[0])
                labels.add(model.names[cls])
        return sorted(labels)

    def image_text_alignment(self, image_path: str, text: str) -> float:
        """
        CLIP-based semantic alignment score between an image and text.
        Both are embedded in the SAME CLIP vector space, so cosine similarity
        directly measures how well the caption describes the image.
        Returns a float in [-1, 1]. Typical aligned pair: 0.25–0.45.
        """
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        img_vec = self._clip_image_embed(img)
        txt_vec = self._clip_text_embed(text)
        return float(np.dot(img_vec, txt_vec))

    def process_image(self, image_path: str, caption: str = "") -> Dict[str, Any]:
        """
        Full image pipeline. Returns a dict with:
          - embedding      : 512-dim CLIP vector (for Qdrant)
          - object_tags    : list of YOLO labels
          - alignment_score: CLIP image-caption cosine similarity (if caption given)
        """
        t0 = time.perf_counter()

        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        clip_vec = self._clip_image_embed(img)

        tags = self.detect_objects(image_path)

        alignment = 1.0
        if caption:
            txt_vec = self._clip_text_embed(caption)
            alignment = float(np.dot(clip_vec, txt_vec))

        logger.debug("image processed in %.0fms", (time.perf_counter() - t0) * 1000)
        return {
            "embedding": clip_vec.tolist(),
            "object_tags": tags,
            "alignment_score": float(np.clip(alignment, -1.0, 1.0)),
        }

    # ── ③ VIDEO ───────────────────────────────────────────────────────────────

    def transcribe_audio(self, video_path: str) -> str:
        """
        faster-whisper (tiny, int8) audio transcription.
        ~4x faster than OpenAI Whisper with minimal accuracy loss for
        short social-media clips.
        Returns the transcript string, or an informative placeholder.
        """
        # Images have no audio
        if Path(video_path).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}:
            return "[No Audio — Image]"

        model = self._get_whisper()
        try:
            segments, info = model.transcribe(
                video_path,
                beam_size=self._cfg().WHISPER_BEAM_SIZE,
                language=None,         # auto-detect language
                vad_filter=True,       # skip silence — faster
                vad_parameters={"min_silence_duration_ms": 500},
            )
            transcript = " ".join(seg.text for seg in segments).strip()
            logger.debug("whisper: detected lang=%s, transcript_len=%d",
                         info.language, len(transcript))
            return transcript or "[No Speech Detected]"
        except Exception as exc:
            logger.warning("Whisper failed on %s: %s", video_path, exc)
            return "[Transcription Failed]"

    def embed_video_frames(self, video_path: str) -> List[float]:
        """
        Sample VIDEO_FRAME_SAMPLES frames from the video, embed each with CLIP,
        and return the L2-normalised average — the video's 'visual fingerprint'.

        This replaces LLaVA entirely. No generative model, no GPU required.
        ~100ms per frame × 8 frames = ~800ms total on CPU.
        Result: 512-dim normalised CLIP vector.
        """
        # Static image shortcut
        if Path(video_path).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            return self.embed_image(video_path)

        import cv2
        from PIL import Image

        cfg = self._cfg()
        n = cfg.VIDEO_FRAME_SAMPLES
        max_sec = cfg.VIDEO_MAX_DURATION_SEC

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        max_frames = int(fps * max_sec)
        effective_total = min(total, max_frames)

        if effective_total <= 0:
            cap.release()
            logger.warning("embed_video_frames: could not read %s", video_path)
            return [0.0] * 512

        # Evenly spaced sample indices
        sample_idx = set(
            int(effective_total * i / n) for i in range(n)
        )

        frame_vecs: List[np.ndarray] = []
        fi = 0
        while cap.isOpened() and fi < effective_total:
            ret, frame = cap.read()
            if not ret:
                break
            if fi in sample_idx:
                pil = Image.fromarray(
                    cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                )
                frame_vecs.append(self._clip_image_embed(pil))
            fi += 1
        cap.release()

        if not frame_vecs:
            return [0.0] * 512

        avg = np.mean(frame_vecs, axis=0)
        return self._l2(avg).tolist()

    def detect_objects_video(self, video_path: str) -> List[str]:
        """
        YOLOv8n object detection sampled across video frames.
        Uses the same sample indices as embed_video_frames for consistency.
        """
        if Path(video_path).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            return self.detect_objects(video_path)

        import cv2

        cfg = self._cfg()
        n = cfg.VIDEO_FRAME_SAMPLES
        model = self._get_yolo()

        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return []

        sample_idx = set(int(total * i / n) for i in range(n))
        labels: set[str] = set()
        fi = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            if fi in sample_idx:
                results = model(frame, verbose=False)
                for r in results:
                    for box in r.boxes:
                        labels.add(model.names[int(box.cls[0])])
            fi += 1
        cap.release()
        return sorted(labels)

    def process_video(self, video_path: str, caption: str = "") -> Dict[str, Any]:
        """
        Full video pipeline. Returns a dict with:
          - embedding         : 512-dim CLIP visual fingerprint (for Qdrant)
          - transcript        : faster-whisper transcription
          - transcript_vector : 384-dim MiniLM embed of transcript (for payload search)
          - object_tags       : YOLO object labels
          - alignment_score   : CLIP visual-vs-caption cosine similarity
          - summary_text      : human-readable content summary (for payload)
        """
        t0 = time.perf_counter()

        # Run the three lightweight parallel-friendly pipelines
        clip_vec = np.array(self.embed_video_frames(video_path))
        transcript = self.transcribe_audio(video_path)
        tags = self.detect_objects_video(video_path)

        # Transcript embedding (MiniLM, 384-dim) — stored in payload for text search
        transcript_vec = self.embed_text(transcript) if transcript and not transcript.startswith("[") else [0.0] * 384

        # Semantic alignment score (CLIP image vs CLIP text — same vector space)
        alignment = 1.0
        if caption:
            caption_clip = self._clip_text_embed(caption)
            alignment = float(np.dot(clip_vec, caption_clip))

        tags_str = ", ".join(tags) if tags else "none detected"
        summary = f"Objects: {tags_str}. Audio: {transcript}"

        logger.info("video processed in %.2fs | tags=%d | transcript_len=%d",
                    time.perf_counter() - t0, len(tags), len(transcript))

        return {
            "embedding": clip_vec.tolist(),                        # 512-dim CLIP
            "transcript": transcript,
            "transcript_vector": transcript_vec,                   # 384-dim MiniLM
            "object_tags": tags,
            "alignment_score": float(np.clip(alignment, -1.0, 1.0)),
            "summary_text": summary,
        }

    # ── Cross-modal helpers ───────────────────────────────────────────────────

    def text_to_clip_vector(self, text: str) -> List[float]:
        """
        Embed text in CLIP's 512-dim space.
        Use when you want to compare text against image/video CLIP embeddings.
        """
        return self._clip_text_embed(text).tolist()

    def vector_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """
        Cosine similarity between two pre-computed normalised vectors.
        O(dim) — ~0.01ms for 512-dim.
        """
        a, b = np.array(vec_a), np.array(vec_b)
        return float(np.dot(a, b))


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton (one per worker process)
# ─────────────────────────────────────────────────────────────────────────────

_processor: Optional[MLProcessor] = None


def get_processor() -> MLProcessor:
    """Return the process-level MLProcessor singleton."""
    global _processor
    if _processor is None:
        _processor = MLProcessor()
    return _processor
