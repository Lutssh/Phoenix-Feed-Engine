import requests
import time
import concurrent.futures
import json
import random

URL_FEED = "http://localhost:3000/feed"
URL_INGEST = "http://localhost:3000/ingest"
CONCURRENT_REQUESTS = 50
TOTAL_REQUESTS = 500

def get_feed(user_id, candidate_count=None, limit=20):
    payload = {"user_id": user_id, "limit": limit}
    if candidate_count:
        payload["candidate_count"] = candidate_count
        
    try:
        start = time.time()
        response = requests.post(URL_FEED, json=payload)
        latency = (time.time() - start) * 1000
        return response.status_code, latency, len(response.json().get("feed", []))
    except Exception as e:
        return 0, 0, 0

def ingest_post(i):
    payload = {
        "event_type": "new_post",
        "user_id": 0,
        "payload": {
            "id": 1000 + i,
            "author_id": 99,
            "text": f"Presence-aware post #{i}"
        }
    }
    try:
        requests.post(URL_INGEST, json=payload)
    except:
        pass

def run_benchmark():
    print("--- Phase 1: Marking Users Online (Heartbeat) ---")
    # Users 1-5 perform a feed request to become "online"
    for i in range(1, 6):
        get_feed(i)
    print("Users 1-5 are now online.")

    print("\n--- Phase 2: Ingesting Posts (Fan-out to Online Users) ---")
    start_ingest = time.time()
    for i in range(20):
        ingest_post(i)
    print(f"Ingested 20 posts. Fan-out should only have hit users 1-5. Total time: {(time.time()-start_ingest)*1000:.2f}ms")

    print("\n--- Phase 3: Verifying Push-Hits (Online Users) ---")
    for i in range(1, 6):
        status, latency, count = get_feed(i, limit=10)
        # These should be fast and come from the precomputed queue
        print(f"User {i}: {count} posts from Push queue in {latency:.2f}ms")

    print("\n--- Phase 4: Discovery Scale (Offline/New Users) ---")
    print(f"Simulating {TOTAL_REQUESTS} requests with 5,000 candidates each (forcing Pull)...")
    
    start_time = time.time()
    pull_latencies = []
    success_count = 0

    # User IDs > 1000 won't have precomputed feeds
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        futures = [executor.submit(get_feed, 1000 + i, 5000) for i in range(TOTAL_REQUESTS)]
        
        for future in concurrent.futures.as_completed(futures):
            status, latency, count = future.result()
            if status == 200:
                success_count += 1
                pull_latencies.append(latency)

    total_time = time.time() - start_time
    avg_pull = sum(pull_latencies) / len(pull_latencies) if pull_latencies else 0
    throughput = success_count / total_time

    print(f"\n--- Heavy Pull Benchmark Results ---")
    print(f"Total Time: {total_time:.2f}s")
    print(f"Throughput: {throughput:.2f} req/sec")
    print(f"Avg Pull Latency (5k candidates): {avg_pull:.2f} ms")

if __name__ == "__main__":
    run_benchmark()