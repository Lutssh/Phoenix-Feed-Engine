import sys
import os
import time
import json
import redis
import logging
from ingest_video import ingest_video
from smart_ingestion.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_description(file_path):
    if not os.path.exists(file_path):
        logger.error(f"File '{file_path}' not found.")
        return

    logger.info(f"\n🚀 Starting Neural Analysis for: {os.path.basename(file_path)}")
    logger.info("   (This triggers CLIP, Whisper, and YOLO in parallel)")
    
    # Trigger pipeline with a dummy caption
    task = ingest_video(file_path, caption="Verification Test") 
    
    logger.info(f"   Task ID: {task.id}")
    logger.info("⏳ Processing... (This can take 30-60s on first run to load models)")
    
    # Wait for result
    try:
        # CC-09: Reduced timeout to 120s
        result = task.get(timeout=120, propagate=True) 
        
        # Fetch the full rich data from Redis
        r = redis.from_url(settings.REDIS_URL)
        # Use the same post_id as ingest_video.py which uses post_id as key
        # In ingest_video.py, post_id is a required arg. 
        # But here we call ingest_video(file_path, ...) so file_path is used as post_id?
        # Let's check ingest_video signature in video_worker.py
        # def ingest_video(video_path, post_id, caption="", metadata=None)
        # Wait, test_description calls ingest_video(file_path, caption="...") 
        # But ingest_video has post_id as SECOND arg.
        
        # Re-check test_description_quality.py original call:
        # task = ingest_video(file_path, caption="Verification Test")
        # And ingest_video.py:
        # from smart_ingestion.workers.video_worker import ingest_video
        
        # Let's check ingest_video in video_worker.py:
        # def ingest_video(video_path: str, post_id: str, caption: str = "", metadata: Optional[Dict] = None):
        
        # Original test_description_quality.py was BUGGY: it passed caption as post_id!
        
        post_id = "test_post_id"
        task = ingest_video(file_path, post_id=post_id, caption="Verification Test")
        result = task.get(timeout=120, propagate=True)

        cache_key = f"neural_context:{post_id}"
        data = r.get(cache_key)
        
        if data:
            parsed = json.loads(data)
            
            print("\n" + "="*60)
            print(f"RESULTS FOR: {os.path.basename(file_path)}")
            print("="*60)
            
            # CC-10: Remove LLaVA, update for new pipeline
            print(f"\n🤖 VISUAL ALIGNMENT (CLIP):")
            print(f'Score: {parsed.get("alignment_score", "N/A")}')
            
            print(f"\n🔍 DETECTED OBJECTS (YOLOv8n):")
            tags = parsed.get('object_tags', [])
            if tags:
                print(f"[{', '.join(tags)}]")
            else:
                print("[None detected]")
            
            print(f"\n🎤 AUDIO TRANSCRIPT (Whisper):")
            print(f'"{parsed.get("transcript", "N/A")}"')
            
            print("="*60)
            print("✅ Verification Complete. Does this description match the content?")
        else:
            print(f"❌ Error: Result reported done, but data missing from Redis cache at {cache_key}.")

    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        print("Note: Ensure Redis and Celery workers are running.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_description_quality.py <path_to_video_or_image>")
        print("Example: python test_description_quality.py samples/my_cat.mp4")
    else:
        test_description(sys.argv[1])
