"""
ingest_video.py  (updated — uses smart_ingestion pipeline)
"""
import argparse
import logging
from smart_ingestion.workers.video_worker import ingest_video

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    logger.info(f"✅ Pipeline triggered. Task ID: {res.id}")
