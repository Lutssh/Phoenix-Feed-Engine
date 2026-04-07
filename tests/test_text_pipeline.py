import time
import redis
import json
from ingest_text import ingest_text
from smart_ingestion.config import settings

def test_text_pipeline():
    post_id = "test_text_123"
    text = "The quick brown fox jumps over the lazy dog."
    
    print(f"🧪 Testing Text Ingestion for post_id: {post_id}")
    print(f"📝 Content: {text}")
    
    res = ingest_text(text, post_id)
    print(f"✅ Triggered task: {res.id}")
    
    # Connect to Redis to verify caching
    r = redis.from_url(settings.REDIS_URL)
    cache_key = f"neural_context:{post_id}"
    
    print("⏳ Waiting for Redis cache to be populated...")
    for _ in range(10):
        time.sleep(1)
        data = r.get(cache_key)
        if data:
            print("✅ Data found in Redis!")
            parsed = json.loads(data)
            print(f"📊 Payload: {json.dumps(parsed['payload'], indent=2)}")
            print(f"🧬 Embedding size: {len(parsed['embedding'])}")
            return
            
    print("❌ Timeout: Data not found in Redis.")

if __name__ == "__main__":
    test_text_pipeline()
