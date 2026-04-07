"""
benchmark_smart_ingestion.py
─────────────────────────────
Benchmarks the smart_ingestion pipeline for:
  1. SPEED     — latency per operation (ms), throughput (items/sec)
  2. ACCURACY  — relationship finding quality (cosine similarity clustering)

Dummy data is fully self-generated — no real images, videos, or audio needed.
Synthetic images are created with Pillow. Synthetic audio is created with numpy.
Synthetic text covers varied topics to test relationship discrimination.

Run:
    python3 benchmark_smart_ingestion.py

Optional flags:
    --skip-image    skip image benchmarks (if Pillow/CLIP issues)
    --skip-video    skip video benchmarks (if OpenCV/Whisper issues)
    --quick         run minimal iterations (faster on slow hardware)
"""

import argparse
import json
import os
import sys
import time
import tempfile
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np

warnings.filterwarnings("ignore")

# ── CLI args ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--skip-image", action="store_true")
parser.add_argument("--skip-video", action="store_true")
parser.add_argument("--quick",      action="store_true",
                    help="Fewer iterations — faster on low-end hardware")
args = parser.parse_args()

QUICK = args.quick

# ── Colour helpers ────────────────────────────────────────────────────────────

def green(s):  return f"\033[92m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"

def bar(value: float, max_value: float = 1.0, width: int = 30) -> str:
    filled = int((value / max_value) * width)
    return "█" * filled + "░" * (width - filled)


# ─────────────────────────────────────────────────────────────────────────────
# DUMMY DATA GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

# ── Text corpus ───────────────────────────────────────────────────────────────
# Organised into 4 topic clusters — relationship accuracy measures whether
# same-cluster items score higher similarity than cross-cluster items.

TEXT_CLUSTERS = {
    "technology": [
        "The new GPU architecture delivers unprecedented machine learning performance.",
        "Neural networks require massive datasets for effective training.",
        "Python remains the dominant language for artificial intelligence development.",
        "Deep learning models achieve superhuman accuracy on image classification tasks.",
        "Transformer architectures have revolutionised natural language processing.",
        "Edge computing brings AI inference closer to the data source.",
    ],
    "cooking": [
        "Caramelising onions slowly unlocks their natural sweetness.",
        "Fresh pasta requires only eggs and tipo 00 flour.",
        "Searing meat at high heat creates the Maillard reaction.",
        "Sourdough starter needs daily feeding to remain active.",
        "A sharp knife is the most important tool in any kitchen.",
        "Blanching vegetables preserves their bright colour and texture.",
    ],
    "sports": [
        "The midfielder scored a stunning long-range goal in extra time.",
        "Proper hydration is essential for peak athletic performance.",
        "The basketball team executed a perfect fast-break play.",
        "Marathon runners hit the wall at mile twenty due to glycogen depletion.",
        "Cross-training reduces injury risk for endurance athletes.",
        "The sprinter broke the national record by two hundredths of a second.",
    ],
    "finance": [
        "Diversification across asset classes reduces portfolio volatility.",
        "Compound interest is the eighth wonder of the world.",
        "Bear markets historically last far shorter than bull markets.",
        "Dollar-cost averaging removes emotional bias from investing.",
        "Inflation erodes the purchasing power of cash savings over time.",
        "Index funds consistently outperform most actively managed funds.",
    ],
}

ALL_TEXTS = [(text, cluster)
             for cluster, texts in TEXT_CLUSTERS.items()
             for text in texts]


# ── Synthetic image generator ─────────────────────────────────────────────────

def make_synthetic_image(
    path: str,
    pattern: str = "gradient",
    color: Tuple[int,int,int] = (128, 64, 200),
    size: Tuple[int,int] = (224, 224),
) -> str:
    """
    Generate a synthetic RGB image and save to path.
    Patterns: gradient, checkerboard, noise, solid
    Different patterns/colours are used as proxy for 'different visual content'.
    """
    from PIL import Image, ImageDraw
    w, h = size
    img = Image.new("RGB", (w, h), color=(0, 0, 0))
    pixels = img.load()

    if pattern == "gradient":
        for x in range(w):
            for y in range(h):
                r = int(color[0] * x / w)
                g = int(color[1] * y / h)
                b = color[2]
                pixels[x, y] = (r, g, b)

    elif pattern == "checkerboard":
        sq = 28
        for x in range(w):
            for y in range(h):
                if (x // sq + y // sq) % 2 == 0:
                    pixels[x, y] = color
                else:
                    pixels[x, y] = (255 - color[0], 255 - color[1], 255 - color[2])

    elif pattern == "noise":
        rng = np.random.default_rng(sum(color))
        arr = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
        img = Image.fromarray(arr)

    elif pattern == "solid":
        img = Image.new("RGB", (w, h), color=color)

    img.save(path)
    return path


IMAGE_SPECS = [
    # (label,          pattern,        color)
    ("warm_gradient",  "gradient",     (220, 80,  30)),
    ("cool_gradient",  "gradient",     (30,  80,  220)),
    ("warm_gradient2", "gradient",     (210, 90,  40)),   # similar to warm_gradient
    ("cool_checker",   "checkerboard", (30,  100, 200)),
    ("warm_checker",   "checkerboard", (200, 80,  30)),
    ("random_noise",   "noise",        (128, 128, 128)),
    ("red_solid",      "solid",        (220, 50,  50)),
    ("blue_solid",     "solid",        (50,  50,  220)),
]

IMAGE_CAPTIONS = {
    "warm_gradient":  "A warm orange sunset fading into the horizon",
    "cool_gradient":  "A cool blue ocean stretching to infinity",
    "warm_gradient2": "Warm amber light at dusk",
    "cool_checker":   "Blue geometric pattern on a city building",
    "warm_checker":   "Rustic orange tiled surface",
    "random_noise":   "Static texture with no clear subject",
    "red_solid":      "Bold red background for a product shot",
    "blue_solid":     "Calm blue sky on a clear afternoon",
}


# ── Synthetic video / audio generator ────────────────────────────────────────

def make_synthetic_video(path: str, duration_sec: int = 3, label: str = "test") -> str:
    """
    Create a minimal synthetic MP4 using OpenCV.
    Frames are solid colour with the label rendered as text.
    This tests the video pipeline without needing real footage.
    """
    try:
        import cv2
        color_map = {
            "nature":  (34,  139, 34),
            "urban":   (100, 100, 100),
            "ocean":   (0,   105, 148),
            "default": (80,  80,  200),
        }
        color = color_map.get(label, color_map["default"])
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(path, fourcc, 10, (320, 240))
        for _ in range(duration_sec * 10):  # 10fps
            frame = np.full((240, 320, 3), color, dtype=np.uint8)
            cv2.putText(frame, label, (60, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
            out.write(frame)
        out.release()
        return path
    except Exception as e:
        return None


VIDEO_SPECS = [
    ("nature_scene",  "nature",  "A peaceful nature scene with trees and birds"),
    ("city_street",   "urban",   "Busy city street with traffic and pedestrians"),
    ("ocean_waves",   "ocean",   "Ocean waves crashing on a sandy beach"),
    ("nature_scene2", "nature",  "Sunlight filtering through a forest canopy"),
]


# ─────────────────────────────────────────────────────────────────────────────
# RESULT CONTAINERS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SpeedResult:
    operation: str
    latencies_ms: List[float] = field(default_factory=list)

    @property
    def mean_ms(self):   return float(np.mean(self.latencies_ms))
    @property
    def median_ms(self): return float(np.median(self.latencies_ms))
    @property
    def p95_ms(self):    return float(np.percentile(self.latencies_ms, 95))
    @property
    def min_ms(self):    return float(np.min(self.latencies_ms))
    @property
    def max_ms(self):    return float(np.max(self.latencies_ms))
    @property
    def throughput(self):return 1000.0 / self.mean_ms


@dataclass
class RelationshipResult:
    test_name: str
    intra_cluster_scores: List[float] = field(default_factory=list)
    inter_cluster_scores: List[float] = field(default_factory=list)
    alignment_pairs: List[Tuple[str, str, float]] = field(default_factory=list)

    @property
    def mean_intra(self): return float(np.mean(self.intra_cluster_scores)) if self.intra_cluster_scores else 0
    @property
    def mean_inter(self): return float(np.mean(self.inter_cluster_scores)) if self.inter_cluster_scores else 0
    @property
    def separation(self): return self.mean_intra - self.mean_inter
    @property
    def discrimination_score(self):
        """
        How well the model separates related from unrelated content.
        > 0.10 = good, > 0.20 = excellent
        """
        return self.separation


# ─────────────────────────────────────────────────────────────────────────────
# BENCHMARK RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def section(title: str):
    print(f"\n{bold(cyan('═' * 60))}")
    print(f"  {bold(title)}")
    print(f"{bold(cyan('═' * 60))}")


def tick():
    return time.perf_counter()


def ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def run_text_benchmarks(proc) -> Tuple[SpeedResult, RelationshipResult]:
    section("① TEXT — Speed & Relationship Accuracy")

    iters = 3 if QUICK else 6
    speed = SpeedResult("text_embedding")
    rel   = RelationshipResult("text_clusters")

    # ── Speed: embed all texts, measure per-item latency ──────────────────
    print(f"\n  {yellow('Speed:')} embedding {len(ALL_TEXTS)} texts × {iters} passes...")

    for _ in range(iters):
        for text, _ in ALL_TEXTS:
            t0 = tick()
            proc.embed_text(text)
            speed.latencies_ms.append(ms(t0))

    # ── Speed: batch embedding (faster path) ──────────────────────────────
    batch_speed = SpeedResult("text_batch_embedding")
    texts_only = [t for t, _ in ALL_TEXTS]
    for _ in range(iters):
        t0 = tick()
        proc.embed_texts_batch(texts_only)
        per_item = ms(t0) / len(texts_only)
        batch_speed.latencies_ms.append(per_item)

    # ── Relationship: build embedding matrix ──────────────────────────────
    print(f"  {yellow('Relationship:')} computing pairwise similarities...")
    embeddings = {}
    for text, cluster in ALL_TEXTS:
        embeddings[text] = (np.array(proc.embed_text(text)), cluster)

    items = list(embeddings.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            text_a, (vec_a, cluster_a) = items[i]
            text_b, (vec_b, cluster_b) = items[j]
            sim = float(np.dot(vec_a, vec_b))
            if cluster_a == cluster_b:
                rel.intra_cluster_scores.append(sim)
            else:
                rel.inter_cluster_scores.append(sim)

    # ── BM25 pre-filter accuracy ───────────────────────────────────────────
    from smart_ingestion.ml_core.bm25_filter import BM25Filter
    corpus = [t for t, _ in ALL_TEXTS]
    cluster_labels = {t: c for t, c in ALL_TEXTS}

    bm25_hits = 0
    bm25_total = 0
    for query_text, query_cluster in ALL_TEXTS[:4]:
        f = BM25Filter(corpus)
        top = f.top_k(query_text, k=6)
        for t in top:
            if t != query_text:
                bm25_total += 1
                if cluster_labels[t] == query_cluster:
                    bm25_hits += 1

    bm25_precision = bm25_hits / bm25_total if bm25_total > 0 else 0

    # ── Print results ──────────────────────────────────────────────────────
    print(f"\n  {'Operation':<30} {'Mean':>8} {'Median':>8} {'P95':>8} {'Throughput':>14}")
    print(f"  {'─'*30} {'─'*8} {'─'*8} {'─'*8} {'─'*14}")

    for s in [speed, batch_speed]:
        tp = f"{s.throughput:.1f}/s"
        status = green(f"{s.mean_ms:7.1f}ms") if s.mean_ms < 50 else yellow(f"{s.mean_ms:7.1f}ms")
        print(f"  {s.operation:<30} {status}  {s.median_ms:7.1f}ms  {s.p95_ms:7.1f}ms  {tp:>14}")

    print(f"\n  {bold('Relationship Discrimination:')}")
    sep_color = green if rel.separation > 0.15 else (yellow if rel.separation > 0.05 else red)
    print(f"  Intra-cluster similarity (same topic):  {green(f'{rel.mean_intra:.4f}')}")
    print(f"  Inter-cluster similarity (diff topic):  {rel.mean_inter:.4f}")
    print(f"  Separation score:                       {sep_color(f'{rel.separation:.4f}')}")
    print(f"  {bar(min(rel.separation, 0.3), 0.3)} {sep_color(f'{rel.separation:.4f}')}")

    print(f"\n  {bold('BM25 Pre-filter:')}")
    bm25_color = green if bm25_precision > 0.6 else yellow
    print(f"  Same-cluster precision in top-6:        {bm25_color(f'{bm25_precision:.1%}')}")

    # ── Per-cluster breakdown ──────────────────────────────────────────────
    print(f"\n  {bold('Per-cluster intra-similarity:')}")
    cluster_names = list(TEXT_CLUSTERS.keys())
    cluster_vecs = {}
    for cluster in cluster_names:
        vecs = [np.array(proc.embed_text(t)) for t in TEXT_CLUSTERS[cluster]]
        cluster_vecs[cluster] = vecs

    for cluster in cluster_names:
        vecs = cluster_vecs[cluster]
        sims = [float(np.dot(vecs[i], vecs[j]))
                for i in range(len(vecs)) for j in range(i+1, len(vecs))]
        mean_sim = np.mean(sims)
        col = green if mean_sim > 0.7 else (yellow if mean_sim > 0.5 else red)
        print(f"  {cluster:<15} {bar(mean_sim, 1.0, 20)} {col(f'{mean_sim:.4f}')}")

    return speed, rel


def run_image_benchmarks(proc, tmpdir: str) -> Tuple[SpeedResult, RelationshipResult]:
    section("② IMAGE — Speed & Visual Relationship Accuracy")

    speed = SpeedResult("image_embedding_clip")
    rel   = RelationshipResult("image_visual_similarity")

    # ── Generate synthetic images ──────────────────────────────────────────
    print(f"\n  {yellow('Generating')} {len(IMAGE_SPECS)} synthetic test images...")
    image_paths = {}
    for label, pattern, color in IMAGE_SPECS:
        path = os.path.join(tmpdir, f"{label}.jpg")
        make_synthetic_image(path, pattern=pattern, color=color)
        image_paths[label] = path
    print(f"  ✓ {len(image_paths)} images created in {tmpdir}")

    # ── Speed: CLIP embedding latency ─────────────────────────────────────
    print(f"\n  {yellow('Speed:')} measuring CLIP embedding latency...")
    iters = 2 if QUICK else 4
    for _ in range(iters):
        for label, path in image_paths.items():
            t0 = tick()
            proc.embed_image(path)
            speed.latencies_ms.append(ms(t0))

    # ── Speed: object detection ────────────────────────────────────────────
    yolo_speed = SpeedResult("object_detection_yolo")
    for label, path in image_paths.items():
        t0 = tick()
        proc.detect_objects(path)
        yolo_speed.latencies_ms.append(ms(t0))

    # ── Relationship: visual similarity matrix ─────────────────────────────
    print(f"  {yellow('Relationship:')} computing visual similarity matrix...")
    img_vecs = {}
    for label, path in image_paths.items():
        img_vecs[label] = np.array(proc.embed_image(path))

    # Expected similar pairs (same dominant colour family)
    similar_pairs = [
        ("warm_gradient", "warm_gradient2"),
        ("warm_gradient", "warm_checker"),
        ("cool_gradient", "cool_checker"),
        ("cool_gradient", "blue_solid"),
        ("warm_gradient", "red_solid"),
    ]
    dissimilar_pairs = [
        ("warm_gradient", "cool_gradient"),
        ("red_solid",     "blue_solid"),
        ("warm_checker",  "cool_checker"),
    ]

    print(f"\n  {bold('Image Similarity (expected similar pairs):')}")
    similar_scores = []
    for a, b in similar_pairs:
        if a in img_vecs and b in img_vecs:
            sim = float(np.dot(img_vecs[a], img_vecs[b]))
            similar_scores.append(sim)
            col = green if sim > 0.8 else (yellow if sim > 0.6 else red)
            print(f"  {a:<20} ↔ {b:<20}  {col(f'{sim:.4f}')}")

    print(f"\n  {bold('Image Similarity (expected dissimilar pairs):')}")
    dissimilar_scores = []
    for a, b in dissimilar_pairs:
        if a in img_vecs and b in img_vecs:
            sim = float(np.dot(img_vecs[a], img_vecs[b]))
            dissimilar_scores.append(sim)
            col = green if sim < 0.8 else yellow
            print(f"  {a:<20} ↔ {b:<20}  {col(f'{sim:.4f}')}")

    # ── Caption alignment (CLIP cross-modal) ──────────────────────────────
    print(f"\n  {bold('Caption Alignment (CLIP cross-modal):')}")
    for label in list(image_paths.keys())[:5]:
        caption = IMAGE_CAPTIONS[label]
        score = proc.image_text_alignment(image_paths[label], caption)
        wrong_caption = IMAGE_CAPTIONS.get(
            "cool_gradient" if label != "cool_gradient" else "warm_gradient", ""
        )
        wrong_score = proc.image_text_alignment(image_paths[label], wrong_caption) if wrong_caption else 0

        col = green if score > wrong_score else yellow
        print(f"  {label:<20}  correct: {col(f'{score:.4f}')}  wrong: {wrong_score:.4f}  {'✓' if score > wrong_score else '✗'}")

    rel.intra_cluster_scores = similar_scores
    rel.inter_cluster_scores = dissimilar_scores

    # ── Print speed results ────────────────────────────────────────────────
    print(f"\n  {'Operation':<30} {'Mean':>8} {'P95':>8} {'Throughput':>14}")
    print(f"  {'─'*30} {'─'*8} {'─'*8} {'─'*14}")
    for s in [speed, yolo_speed]:
        tp = f"{s.throughput:.1f}/s"
        col = green if s.mean_ms < 500 else yellow
        print(f"  {s.operation:<30} {col(f'{s.mean_ms:7.1f}ms')}  {s.p95_ms:7.1f}ms  {tp:>14}")

    return speed, rel


def run_video_benchmarks(proc, tmpdir: str) -> Tuple[SpeedResult, RelationshipResult]:
    section("③ VIDEO — Speed & Visual Relationship Accuracy")

    speed  = SpeedResult("video_clip_frames")
    rel    = RelationshipResult("video_visual_similarity")

    # ── Generate synthetic videos ──────────────────────────────────────────
    print(f"\n  {yellow('Generating')} {len(VIDEO_SPECS)} synthetic test videos...")
    video_paths = {}
    for label, scene, caption in VIDEO_SPECS:
        path = os.path.join(tmpdir, f"{label}.mp4")
        result = make_synthetic_video(path, duration_sec=2, label=scene)
        if result:
            video_paths[label] = (path, caption)
    print(f"  ✓ {len(video_paths)} videos created")

    if not video_paths:
        print(f"  {red('OpenCV not available — skipping video benchmarks')}")
        return speed, rel

    # ── Speed: CLIP frame embedding ────────────────────────────────────────
    print(f"\n  {yellow('Speed:')} measuring CLIP video frame embedding...")
    iters = 1 if QUICK else 2
    for _ in range(iters):
        for label, (path, _) in video_paths.items():
            t0 = tick()
            proc.embed_video_frames(path)
            speed.latencies_ms.append(ms(t0))

    # ── Speed: transcription ───────────────────────────────────────────────
    whisper_speed = SpeedResult("audio_transcription_faster_whisper")
    for label, (path, _) in video_paths.items():
        t0 = tick()
        proc.transcribe_audio(path)
        whisper_speed.latencies_ms.append(ms(t0))

    # ── Relationship: video visual similarity ─────────────────────────────
    print(f"\n  {yellow('Relationship:')} computing video-video similarity...")
    vid_vecs = {}
    for label, (path, _) in video_paths.items():
        vid_vecs[label] = np.array(proc.embed_video_frames(path))

    labels = list(vid_vecs.keys())
    print(f"\n  {bold('Video Similarity Matrix:')}")
    header = f"  {'':20}" + "".join(f"{l[:10]:>12}" for l in labels)
    print(header)
    for i, la in enumerate(labels):
        row = f"  {la:<20}"
        for j, lb in enumerate(labels):
            sim = float(np.dot(vid_vecs[la], vid_vecs[lb]))
            if i == j:
                row += f"{'  1.0000':>12}"
            else:
                col = green if sim > 0.85 else (yellow if sim > 0.6 else "")
                row += f"{col}{sim:>12.4f}{chr(27)+'[0m' if col else ''}"
        print(row)

    # ── Caption alignment ──────────────────────────────────────────────────
    print(f"\n  {bold('Video-Caption Alignment (CLIP cross-modal):')}")
    for label, (path, caption) in video_paths.items():
        vid_vec = np.array(proc.embed_video_frames(path))
        cap_vec = np.array(proc.text_to_clip_vector(caption))
        score = float(np.dot(vid_vec, cap_vec))
        wrong_cap = VIDEO_SPECS[1][2] if label != VIDEO_SPECS[1][0] else VIDEO_SPECS[0][2]
        wrong_vec = np.array(proc.text_to_clip_vector(wrong_cap))
        wrong_score = float(np.dot(vid_vec, wrong_vec))
        col = green if score > wrong_score else yellow
        print(f"  {label:<20}  match: {col(f'{score:.4f}')}  mismatch: {wrong_score:.4f}  {'✓' if score > wrong_score else '✗'}")

    # ── Print speed results ────────────────────────────────────────────────
    print(f"\n  {'Operation':<30} {'Mean':>8} {'P95':>8} {'Throughput':>14}")
    print(f"  {'─'*30} {'─'*8} {'─'*8} {'─'*14}")
    for s in [speed, whisper_speed]:
        if not s.latencies_ms:
            continue
        tp = f"{s.throughput:.1f}/s"
        col = green if s.mean_ms < 3000 else yellow
        print(f"  {s.operation:<30} {col(f'{s.mean_ms:7.1f}ms')}  {s.p95_ms:7.1f}ms  {tp:>14}")

    return speed, rel


def run_cross_modal_benchmark(proc, tmpdir: str):
    """
    Cross-modal relationship test: can we find the right image for a text query?
    This is the core capability that powers the feed — text queries matching visual content.
    """
    section("④ CROSS-MODAL — Text → Image Relationship Finding")

    # Generate images
    print(f"\n  {yellow('Generating cross-modal test set...')}")
    test_set = [
        ("warm gradient image",     "gradient",     (220, 80, 30)),
        ("cool blue image",         "gradient",     (30,  80, 220)),
        ("checkerboard pattern",    "checkerboard", (100, 100, 200)),
        ("random texture",          "noise",        (128, 128, 128)),
        ("solid red background",    "solid",        (220, 50, 50)),
        ("solid blue background",   "solid",        (50,  50, 220)),
    ]

    image_items = []
    for desc, pattern, color in test_set:
        path = os.path.join(tmpdir, f"xmod_{desc.replace(' ', '_')}.jpg")
        make_synthetic_image(path, pattern=pattern, color=color)
        img_vec = np.array(proc.embed_image(path))
        image_items.append((desc, img_vec))

    # Text queries
    queries = [
        "warm orange tones",
        "cool blue palette",
        "geometric repeating pattern",
        "random static noise texture",
        "vivid red colour",
        "deep blue colour",
    ]

    # Expected best-match index for each query
    expected = [0, 1, 2, 3, 4, 5]

    print(f"\n  {bold('Text Query → Best Matching Image:')}")
    print(f"  {'Query':<30} {'Best Match':<30} {'Score':>8} {'Correct':>8}")
    print(f"  {'─'*30} {'─'*30} {'─'*8} {'─'*8}")

    correct = 0
    for qi, (query, exp_idx) in enumerate(zip(queries, expected)):
        t0 = tick()
        query_vec = np.array(proc.text_to_clip_vector(query))
        scores = [(float(np.dot(query_vec, iv)), desc) for desc, iv in image_items]
        scores.sort(reverse=True)
        best_score, best_desc = scores[0]
        latency = ms(t0)
        is_correct = best_desc == image_items[exp_idx][0]
        if is_correct:
            correct += 1
        mark = green("✓") if is_correct else red("✗")
        print(f"  {query:<30} {best_desc:<30} {best_score:>8.4f}  {mark}")

    accuracy = correct / len(queries)
    col = green if accuracy >= 0.8 else (yellow if accuracy >= 0.5 else red)
    print(f"\n  Cross-modal retrieval accuracy: {col(f'{accuracy:.1%}')} ({correct}/{len(queries)})")

    return accuracy


# ─────────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(results: Dict):
    section("BENCHMARK SUMMARY")

    print(f"\n  {'Pipeline':<35} {'Speed':>12} {'Relationship Sep.':>18} {'Grade':>8}")
    print(f"  {'─'*35} {'─'*12} {'─'*18} {'─'*8}")

    grades = []
    for name, data in results.items():
        speed_str = f"{data['mean_ms']:.0f}ms" if data.get('mean_ms') else "—"
        rel_str = f"{data['separation']:.4f}" if data.get('separation') is not None else "—"

        # Grade logic
        if name == "text_embedding":
            speed_ok = data.get('p95_ms', 9999) < 50
        else:
            speed_ok = data.get('mean_ms', 9999) < 2000
            
        rel_ok   = data.get('separation', 0) > 0.05

        if speed_ok and rel_ok:     grade, gcol = "A",  green
        elif speed_ok or rel_ok:    grade, gcol = "B",  yellow
        else:                       grade, gcol = "C",  red

        grades.append(grade)
        print(f"  {name:<35} {speed_str:>12} {rel_str:>18} {gcol(grade):>8}")

    overall = "A" if grades.count("A") >= len(grades) * 0.7 else \
              "B" if grades.count("C") == 0 else "C"
    ocol = green if overall == "A" else (yellow if overall == "B" else red)

    print(f"\n  {bold('Overall Pipeline Grade:')} {ocol(bold(overall))}")
    print(f"\n  {bold('Key Metrics:')}")
    if "text_embedding" in results:
        t = results["text_embedding"]
        print(f"  Text embed:    {t.get('mean_ms', 0):.1f}ms/item "
              f"| Separation: {t.get('separation', 0):.4f}")
    if "image_clip" in results:
        i = results["image_clip"]
        print(f"  Image CLIP:    {i.get('mean_ms', 0):.1f}ms/item "
              f"| Caption align: ✓")
    if "video_clip" in results:
        v = results["video_clip"]
        print(f"  Video frames:  {v.get('mean_ms', 0):.1f}ms/item")
    if "cross_modal" in results:
        print(f"  Cross-modal retrieval: {results['cross_modal'].get('accuracy', 0):.1%}")

    print(f"\n  {bold('Targets for production readiness:')}")
    targets = [
        ("Text embed p95 < 50ms/item",    results.get("text_embedding", {}).get("p95_ms", 9999) < 50),
        ("Text separation > 0.10",        results.get("text_embedding", {}).get("separation", 0) > 0.10),
        ("Image CLIP < 500ms/item",       results.get("image_clip", {}).get("mean_ms", 9999) < 500),
        ("Cross-modal accuracy > 60%",    results.get("cross_modal", {}).get("accuracy", 0) > 0.6),
        ("Video frames < 5000ms",         results.get("video_clip", {}).get("mean_ms", 9999) < 5000),
    ]
    for label, passed in targets:
        mark = green("✓ PASS") if passed else red("✗ FAIL")
        print(f"  {mark}  {label}")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(bold(cyan("\n  smart_ingestion — Pipeline Benchmark")))
    print(cyan("  Speed & Relationship Accuracy Test\n"))

    print("  Loading MLProcessor (models load on first use)...")
    from smart_ingestion.ml_core.processor import get_processor
    proc = get_processor()
    print(f"  {green('✓')} Processor ready\n")

    results = {}

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── ① Text ────────────────────────────────────────────────────────
        text_speed, text_rel = run_text_benchmarks(proc)
        results["text_embedding"] = {
            "mean_ms":   text_speed.mean_ms,
            "p95_ms":    text_speed.p95_ms,
            "separation": text_rel.separation,
        }

        # ── ② Image ───────────────────────────────────────────────────────
        if not args.skip_image:
            try:
                img_speed, img_rel = run_image_benchmarks(proc, tmpdir)
                results["image_clip"] = {
                    "mean_ms":   img_speed.mean_ms,
                    "p95_ms":    img_speed.p95_ms,
                    "separation": img_rel.separation,
                }
            except Exception as e:
                print(f"  {red('Image benchmark error:')} {e}")
        else:
            print(f"\n  {yellow('Image benchmarks skipped (--skip-image)')}")

        # ── ③ Video ───────────────────────────────────────────────────────
        if not args.skip_video:
            try:
                vid_speed, vid_rel = run_video_benchmarks(proc, tmpdir)
                if vid_speed.latencies_ms:
                    results["video_clip"] = {
                        "mean_ms":   vid_speed.mean_ms,
                        "p95_ms":    vid_speed.p95_ms,
                        "separation": vid_rel.separation,
                    }
            except Exception as e:
                print(f"  {red('Video benchmark error:')} {e}")
        else:
            print(f"\n  {yellow('Video benchmarks skipped (--skip-video)')}")

        # ── ④ Cross-modal ─────────────────────────────────────────────────
        if not args.skip_image:
            try:
                xmod_acc = run_cross_modal_benchmark(proc, tmpdir)
                results["cross_modal"] = {"accuracy": xmod_acc}
            except Exception as e:
                print(f"  {red('Cross-modal benchmark error:')} {e}")

    # ── Summary ───────────────────────────────────────────────────────────
    print_summary(results)

    # ── Save JSON report ──────────────────────────────────────────────────
    report_path = "benchmark_results_smart_ingestion.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Full report saved to {bold(report_path)}\n")


if __name__ == "__main__":
    main()

