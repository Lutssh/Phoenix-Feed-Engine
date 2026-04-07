import sys
import os
import time
import json
import redis
from ingest_video import ingest_video
from smart_ingestion.config import settings

def test_description(file_path):
    if not os.path.exists(file_path):
        print(f"❌ Error: File '{file_path}' not found.")
        return

    print(f"\n🚀 Starting Neural Analysis for: {os.path.basename(file_path)}")
    print("   (This triggers YOLOv11, Whisper, and Video-LLaVA in parallel)")
    
    # Trigger pipeline with a dummy caption
    task = ingest_video(file_path, caption="Verification Test") 
    
    print(f"   Task ID: {task.id}")
    print("⏳ Processing... (This can take 30-60s on first run to load models)")
    
    # Wait for result
    try:
        # Wait for the Celery task to complete (timeout 10 mins)
        result = task.get(timeout=600) 
        
        # Fetch the full rich data from Redis
        r = redis.from_url(settings.REDIS_URL)
        cache_key = f"neural_context:{file_path}"
        data = r.get(cache_key)
        
        if data:
            parsed = json.loads(data)
            
            print("\n" + "="*60)
            print(f"RESULTS FOR: {os.path.basename(file_path)}")
            print("="*60)
            
            print(f"\n🤖 VISUAL UNDERSTANDING (Video-LLaVA):")
            print(f'"{parsed.get("llava_description", "N/A")}"')
            
            print(f"\n🔍 DETECTED OBJECTS (YOLOv11):")
            tags = parsed.get('yolo_tags', [])
            if tags:
                print(f"[{', '.join(tags)}]")
            else:
                print("[None detected]")
            
            print(f"\n🎤 AUDIO TRANSCRIPT (Whisper):")
            print(f'"{parsed.get("whisper_text", "N/A")}"')
            
            print("="*60)
            print("✅ Verification Complete. Does this description match the content?")
        else:
            print("❌ Error: Result reported done, but data missing from Redis cache.")

    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        print("Note: Ensure Redis and Celery workers are running.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_description_quality.py <path_to_video_or_image>")
        print("Example: python test_description_quality.py samples/my_cat.mp4")
    else:
        test_description(sys.argv[1])
