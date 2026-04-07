import requests
import time
import concurrent.futures
import json

URL = "http://localhost:3000/feed"
CONCURRENT_REQUESTS = 100 # Simulating high concurrency
TOTAL_REQUESTS = 1000

def get_feed(req_id):
    start = time.time()
    try:
        response = requests.post(URL, json={"user_id": req_id, "limit": 50})
        latency = (time.time() - start) * 1000
        if response.status_code != 200:
            print(f"Request failed with status {response.status_code}: {response.text}")
        return response.status_code, latency
    except Exception as e:
        print(f"Request exception: {e}")
        return 0, 0

def run_benchmark():
    print(f"Starting benchmark: {TOTAL_REQUESTS} requests with {CONCURRENT_REQUESTS} concurrency...")
    
    start_time = time.time()
    latencies = []
    success_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        futures = [executor.submit(get_feed, i) for i in range(TOTAL_REQUESTS)]
        
        for future in concurrent.futures.as_completed(futures):
            status, latency = future.result()
            if status == 200:
                success_count += 1
                latencies.append(latency)

    total_time = time.time() - start_time
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    throughput = success_count / total_time

    print(f"\n--- Benchmark Results ---")
    print(f"Total Time: {total_time:.2f}s")
    print(f"Successful Requests: {success_count}/{TOTAL_REQUESTS}")
    print(f"Throughput: {throughput:.2f} req/sec")
    print(f"Avg Latency: {avg_latency:.2f} ms")
    print(f"Min Latency: {min(latencies):.2f} ms" if latencies else "Min Latency: N/A")
    print(f"Max Latency: {max(latencies):.2f} ms" if latencies else "Max Latency: N/A")

if __name__ == "__main__":
    # Wait for service to be up
    print("Ensure the service is running (cargo run --release or docker-compose up) before running this script.")
    run_benchmark()
