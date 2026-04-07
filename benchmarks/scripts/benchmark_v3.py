import requests
import time
import concurrent.futures
import json
import random
from collections import Counter

URL_FEED = "http://localhost:3000/feed"
URL_INGEST = "http://localhost:3000/ingest"
CONCURRENT_REQUESTS = 50
TOTAL_REQUESTS = 1000

def get_feed(user_id, candidate_count=None, limit=20):
    payload = {"user_id": user_id, "limit": limit}
    if candidate_count:
        payload["candidate_count"] = candidate_count
        
    try:
        start = time.time()
        response = requests.post(URL_FEED, json=payload)
        latency = (time.time() - start) * 1000
        data = response.json()
        return response.status_code, latency, data.get("feed_type", "unknown")
    except Exception as e:
        return 0, 0, str(e)

def ingest_post(i):
    payload = {
        "event_type": "new_post",
        "user_id": 0,
        "payload": {
            "id": 10000 + i,
            "author_id": 99,
            "text": f"Real-time update #{i}"
        }
    }
    try:
        requests.post(URL_INGEST, json=payload)
    except:
        pass

def run_benchmark():
    print("--- Phase 1: Warming up Online Users ---")
    online_users = list(range(1, 11)) # Users 1-10
    for uid in online_users:
        get_feed(uid)
    print(f"Users {online_users} are now marked as ONLINE.")

    print("\n--- Phase 2: Simulating High-Volume Fan-out ---")
    # This happens in the background on the server
    for i in range(50):
        ingest_post(i)
    print("Ingested 50 posts. Server is fanning out to online users in background...")
    time.sleep(1) # Give background tasks a moment

    print("\n--- Phase 3: Measuring Latency by Feed Type ---")
    print(f"Executing {TOTAL_REQUESTS} concurrent requests...")
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        # Mix of online users (Push Hits) and offline/new users (Lite/Pull)
        tasks = []
        for i in range(TOTAL_REQUESTS):
            if i % 4 == 0:
                uid = random.randint(1, 10) # Online
                tasks.append(executor.submit(get_feed, uid))
            else:
                uid = 1000 + i # Offline/New
                # Force heavy load on discovery for new users
                tasks.append(executor.submit(get_feed, uid, candidate_count=5000))
        
        for future in concurrent.futures.as_completed(tasks):
            results.append(future.result())

    # Analysis
    stats = {}
    type_counts = Counter()
    
    for status, latency, ftype in results:
        if status == 200:
            type_counts[ftype] += 1
            if ftype not in stats:
                stats[ftype] = []
            stats[ftype].append(latency)

    print("\n" + "="*40)
    print("BENCHMARK V3 RESULTS (Presence & Fast-Start)")
    print("="*40)
    
    for ftype, latencies in stats.items():
        avg = sum(latencies)/len(latencies)
        p95 = sorted(latencies)[int(len(latencies)*0.95)]
        print(f"Type: {ftype.upper()}")
        print(f"  Count:   {len(latencies)}")
        print(f"  Avg Lat: {avg:.2f} ms")
        print(f"  P95 Lat: {p95:.2f} ms")
        print("-" * 20)

    print(f"Total Success: {sum(type_counts.values())}/{TOTAL_REQUESTS}")
    
    if "push" in stats and "lite" in stats:
        improvement = (sum(stats["lite"])/len(stats["lite"])) / (sum(stats["push"])/len(stats["push"]))
        print(f"\nOptimization Insight: Push hits are {improvement:.1f}x faster than Lite pulls.")
    
if __name__ == "__main__":
    run_benchmark()
