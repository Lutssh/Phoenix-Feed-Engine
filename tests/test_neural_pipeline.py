import time
import sys
import os
try:
    import cv2
except ImportError:
    cv2 = None
import numpy as np
from smart_ingestion.utils.qdrant_utils import get_qdrant_client
from ingest_video import ingest_video

def create_dummy_video(filename="test_video.mp4", duration=2):
    """Creates a simple video with a moving rectangle to simulate content."""
    if cv2 is None:
        print("⚠️ OpenCV (cv2) is not installed. Skipping dummy video creation.")
        return None
        
    print(f"🎥 Creating dummy video: {filename}")
    height, width = 224, 224
    fps = 30
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    for i in range(duration * fps):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Draw a moving red square
        x = int((i / (duration * fps)) * (width - 50))
        cv2.rectangle(frame, (x, 50), (x + 40, 90), (0, 0, 255), -1)
        # Add some text to "trick" OCR/Visual models
        cv2.putText(frame, "TEST", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        out.write(frame)

    out.release()
    return filename

def test_pipeline():
    video_path = "test_video.mp4"
    if not os.path.exists(video_path):
        create_dummy_video(video_path)

    # Test Case 1: High Alignment
    caption_match = "A video with a moving red square and text."
    print(f"\n🧪 Test 1: Ingesting with MATCHING caption: '{caption_match}'")
    task_match = ingest_video(video_path, caption=caption_match)
    
    # Test Case 2: Low Alignment
    caption_mismatch = "A video of a dog running in a park."
    print(f"\n🧪 Test 2: Ingesting with MISMATCHING caption: '{caption_mismatch}'")
    task_mismatch = ingest_video(video_path, caption=caption_mismatch)

    print("\n⏳ Waiting for results (this might take a moment if models are loading)...")
    
    # In a real integration test we'd use celery result backend, 
    # but here we'll poll Qdrant for the latest entries.
    client = get_qdrant_client()
    collection_name = "video_meta_context"
    
    # Polling loop
    for _ in range(20):
        time.sleep(2)
        try:
            # Fetch latest 2 points
            res = client.scroll(
                collection_name=collection_name,
                limit=2,
                with_payload=True,
                with_vectors=False
            )[0]
            
            if len(res) >= 2:
                print("\n✅ Results found in Qdrant!")
                for point in res:
                    payload = point.payload
                    score = payload.get("semantic_alignment_score", 0.0)
                    cap = payload.get("caption", "")
                    print(f"   - Caption: '{cap}' | Alignment Score: {score:.4f}")
                
                break
        except Exception as e:
            print(f"   Waiting... ({e})")
            
    print("\n🎉 Test Complete. Check if the 'red square' caption has a higher score than the 'dog' caption.")

if __name__ == "__main__":
    test_pipeline()
