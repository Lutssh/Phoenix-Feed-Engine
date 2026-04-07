"""
smart_ingestion
───────────────
Lightweight neural ingestion pipeline for feed ranking.

Layer         Model                   Size     Dims   Device
──────────────────────────────────────────────────────────────
Text          all-MiniLM-L6-v2        22 MB    384    CPU
Image         CLIP ViT-B/32           350 MB   512    CPU
Video frames  CLIP ViT-B/32           350 MB   512    CPU  (shared)
Audio         faster-whisper tiny     75 MB    —      CPU
Objects       YOLOv8n                 6 MB     —      CPU
Text pre-flt  BM25 (rank_bm25)       0 MB     —      CPU
"""
