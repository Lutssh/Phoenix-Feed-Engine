"""
signals_client.py
─────────────────
Reference implementation for recording user interactions and triggering 
content ingestion from any Python-based backend.

This client ensures that your main application remains lightweight 
while the Rust engine handles ranking and the Python workers handle ML.
"""
import httpx
import logging
from typing import Optional, Dict

# Configuration
RUST_ENGINE_URL = "http://localhost:3000"
logger = logging.getLogger(__name__)

def record_interaction(
    user_id: int, 
    post_id: int, 
    action: str, 
    post_type: str, 
    dwell_ms: int = 0, 
    author_id: int = 0
) -> bool:
    """
    Sends a user interaction event to the Rust Feed Engine.
    
    Actions: like, share, reply, dwell, click, follow, skip, hide, not_interested, report
    Post Types: text, image, video
    """
    payload = {
        "user_id": user_id,
        "post_id": post_id,
        "action": action,
        "post_type": post_type,
        "author_id": author_id,
        "dwell_ms": dwell_ms,
    }
    
    try:
        # Fire-and-forget: we use a short timeout to not block the main app
        with httpx.Client(timeout=0.5) as client:
            response = client.post(f"{RUST_ENGINE_URL}/interaction", json=payload)
            return response.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to record interaction: {e}")
        return False

def trigger_ingestion(
    event_type: str,
    user_id: int,
    payload: Dict
) -> bool:
    """
    Triggers the ingestion pipeline in the Rust Engine.
    Used when a new post is created.
    """
    data = {
        "event_type": event_type,
        "user_id": user_id,
        "payload": payload
    }
    
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.post(f"{RUST_ENGINE_URL}/ingest", json=data)
            return response.status_code == 202
    except Exception as e:
        logger.error(f"Failed to trigger ingestion: {e}")
        return False

# ── Example Usage ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1. Recording a like
    success = record_interaction(user_id=1, post_id=101, action="like", post_type="text")
    print(f"Recorded like: {success}")
    
    # 2. Triggering ingestion for a new post
    post_data = {
        "id": 102,
        "author_id": 5,
        "text": "This is a new post being ingested into the system."
    }
    success = trigger_ingestion(event_type="new_post", user_id=5, payload=post_data)
    print(f"Triggered ingestion: {success}")
