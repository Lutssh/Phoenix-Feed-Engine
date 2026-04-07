import requests
import time
import concurrent.futures
import json
import random
from collections import Counter

URL_FEED = "http://localhost:3000/feed"
URL_INGEST = "http://localhost:3000/ingest"
CONCURRENT_REQUESTS = 100
TOTAL_REQUESTS = 10000 
NUM_ONLINE_USERS = 5000 # Simulating thousands of active users

def get_feed(user_id, candidate_count=None, limit=20):
    payload = {"user_id": user_id, "limit": limit}
    if candidate_count:
        payload["candidate_count"] = candidate_count
        
    try:
        start_wait = time.time()
        response = requests.post(URL_FEED, json=payload)
        wait_time = (time.time() - start_wait) * 1000
        
        data = response.json()
        ftype = data.get("feed_type", "unknown")
        # In a real app, wait_time is what the user feels. 
        # data['latency_ms'] is what the server spent.
        return response.status_code, wait_time, ftype
    except Exception as e:
        return 0, 0, str(e)

def ingest_post(i):
    payload = {
        "event_type": "new_post",
        "user_id": 0,
        "payload": {"id": 20000 + i, "author_id": 88, "text": "Scale test"}
    }
    try: requests.post(URL_INGEST, json=payload)
    except: pass

def run_benchmark():
    print(f"--- Phase 1: Warming up {NUM_ONLINE_USERS} Online Users ---")
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        executor.map(get_feed, range(1, NUM_ONLINE_USERS + 1))
    print(f"Presence Layer updated. {NUM_ONLINE_USERS} users are ONLINE in Redis.")

    print("\n--- Phase 2: Massive Background Fan-out ---")
    start_ingest = time.time()
    for i in range(10):
        ingest_post(i)
    print(f"Ingested 10 posts. Fan-out task for {NUM_ONLINE_USERS} users is running in background.")

    print(f"\n--- Phase 3: Stress Test ({TOTAL_REQUESTS} requests) ---")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        tasks = []
        for i in range(TOTAL_REQUESTS):
            # 20% are online (Push hits), 80% are new/cold (Lite Fast-Start)
            if i % 5 == 0:
                uid = random.randint(1, NUM_ONLINE_USERS)
                tasks.append(executor.submit(get_feed, uid))
            else:
                uid = 50000 + i
                # Force massive 10,000 candidate discovery for cold users
                tasks.append(executor.submit(get_feed, uid, candidate_count=10000))
        
        for future in concurrent.futures.as_completed(tasks):
            results.append(future.result())

    # Analysis
    stats = {}
    type_counts = Counter()
    for status, wait_time, ftype in results:
        if status == 200:
            type_counts[ftype] += 1
            if ftype not in stats: stats[ftype] = []
            stats[ftype].append(wait_time)

    print("\n" + "="*50)
    print(f"BENCHMARK V4: MILLION-USER SCALE SIMULATION")
    print("="*50)
    
    for ftype, waits in stats.items():
        avg = sum(waits)/len(waits)
        p99 = sorted(waits)[int(len(waits)*0.99)]
        print(f"Feed Type: {ftype.upper()}")
        print(f"  Requests:    {len(waits)}")
        print(f"  Avg User Wait: {avg:.2f} ms")
        print(f"  P99 User Wait: {p99:.2f} ms")
        print("-" * 30)

    print(f"Total Throughput: {len(results)/(time.time()-start_ingest):.2f} req/sec")
    print(f"Presence-Aware Success: {type_counts['push']} users got precomputed feeds.")
    print(f"Discovery Cache Success: {type_counts['discovery']} users got in-memory discovery.")
    print(f"Fast-Start Success: {type_counts['lite']} users got instant cold-start feeds.")

if __name__ == "__main__":
    run_benchmark()
