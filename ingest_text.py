import argparse
from smart_ingestion.workers.text_worker import process_text

def ingest_text(text: str, post_id: str, extra_metadata: dict = None):
    print(f"🚀 Starting text ingestion for post: {post_id}")
    # We call it as a delay (async task)
    result = process_text.delay(text, post_id, extra_metadata)
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a text post into the neural pipeline.")
    parser.add_argument("text", help="The text content of the post")
    parser.add_argument("--post_id", help="Unique ID for the post", required=True)
    
    args = parser.parse_args()
    
    res = ingest_text(args.text, args.post_id)
    print(f"✅ Task triggered. Task ID: {res.id}")
