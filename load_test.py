import asyncio
import aiohttp
import argparse
import time
import uuid
import random
import sys
import csv

async def warmup(url, session):
    print(f"Waking up the instance at {url} (this could take 30-50s on free tier)...")
    start = time.time()
    while True:
        try:
            async with session.get(f"{url}/api/voter/current", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status in (200, 404):
                    elapsed = time.time() - start
                    print(f"Instance is awake! Took {elapsed:.2f} seconds.")
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
        if time.time() - start > 120:
            print("Failed to wake up instance after 120 seconds. Aborting.")
            sys.exit(1)

async def simulate_voter(voter_id, url, session, poll_interval, duration, all_requests, test_start_time):
    vote_delay = random.uniform(0.5, 5.0)
    end_time = test_start_time + duration
    has_voted = False
    
    while time.time() < end_time:
        start_poll = time.time()
        poll_data = None
        status = 0
        success = False
        try:
            async with session.get(f"{url}/api/voter/current", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
                poll_data = await resp.json() if status == 200 else None
                success = (status == 200)
        except Exception as e:
            pass
            
        latency = (time.time() - start_poll) * 1000
        all_requests.append((time.time(), 'GET /api/voter/current', latency, status, success))
            
        if not has_voted and poll_data and poll_data.get('status') == 'active' and poll_data.get('question'):
            if time.time() - test_start_time >= vote_delay:
                has_voted = True
                question = poll_data['question']
                option_index = random.randint(0, len(question['options']) - 1)
                payload = {
                    'question_id': question['id'],
                    'option_index': option_index,
                    'voter_id': voter_id
                }
                
                start_vote = time.time()
                v_status = 0
                v_success = False
                try:
                    async with session.post(f"{url}/vote", json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        v_status = resp.status
                        v_success = (v_status in (200, 409))
                except Exception as e:
                    pass
                
                v_latency = (time.time() - start_vote) * 1000
                all_requests.append((time.time(), 'POST /vote', v_latency, v_status, v_success))

        time_to_sleep = poll_interval - (time.time() - start_poll)
        if time_to_sleep > 0:
            await asyncio.sleep(time_to_sleep)
        else:
            await asyncio.sleep(0)

async def main():
    parser = argparse.ArgumentParser(description="Load test for live polling app")
    parser.add_argument("--url", required=True, help="Target URL (e.g. https://your-app.onrender.com)")
    parser.add_argument("--voters", type=int, default=300, help="Number of virtual voters")
    parser.add_argument("--poll-interval", type=float, default=4.0, help="Polling interval in seconds")
    parser.add_argument("--duration", type=float, default=180.0, help="Duration of the load test in seconds")
    args = parser.parse_args()
    
    url = args.url.rstrip('/')
    
    all_requests = []
    
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        await warmup(url, session)
        
        print(f"\nStarting load test with {args.voters} virtual voters for {args.duration} seconds...")
        print(f"Target: {url}")
        print(f"Poll Interval: {args.poll_interval}s\n")
        
        test_start_time = time.time()
        tasks = []
        for _ in range(args.voters):
            voter_id = f"sim-{uuid.uuid4()}"
            tasks.append(asyncio.create_task(simulate_voter(voter_id, url, session, args.poll_interval, args.duration, all_requests, test_start_time)))
            
        await asyncio.gather(*tasks)
        
    # Process results
    polls = [r for r in all_requests if r[1] == 'GET /api/voter/current']
    votes = [r for r in all_requests if r[1] == 'POST /vote']
    
    # Calculate peak RPS
    def get_peak_rps(reqs, start_time, end_time):
        buckets = {}
        for r in reqs:
            t = int(r[0])
            if start_time <= t <= end_time:
                buckets[t] = buckets.get(t, 0) + 1
        return max(buckets.values()) if buckets else 0
        
    start_ts = int(test_start_time)
    peak_rps_burst = get_peak_rps(all_requests, start_ts, start_ts + 10)
    peak_rps_sustained = get_peak_rps(all_requests, start_ts + 11, start_ts + int(args.duration))

    # Write CSV
    with open('load_test_results.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'endpoint', 'response_time_ms', 'status_code', 'success'])
        for r in all_requests:
            writer.writerow(r)
            
    print("--- Load Test Results ---")
    
    overall_success_rate = (sum(1 for r in all_requests if r[4]) / len(all_requests) * 100) if all_requests else 0
    max_p95_latency = 0
    
    def print_stats(name, reqs):
        nonlocal max_p95_latency
        count = len(reqs)
        if count == 0:
            print(f"{name}: No requests made.")
            return
            
        errors = sum(1 for r in reqs if not r[4])
        latencies = sorted([r[2] for r in reqs])
        
        avg_lat = sum(latencies) / count
        min_lat = latencies[0]
        max_lat = latencies[-1]
        p95_lat = latencies[int(count * 0.95)]
        p99_lat = latencies[int(count * 0.99)]
        
        max_p95_latency = max(max_p95_latency, p95_lat)
        
        print(f"{name}:")
        print(f"  Total requests: {count}")
        print(f"  Errors/Timeouts: {errors} ({(errors/count)*100:.1f}%)")
        print(f"  Latency: Min={min_lat:.0f}ms | Avg={avg_lat:.0f}ms | p95={p95_lat:.0f}ms | p99={p99_lat:.0f}ms | Max={max_lat:.0f}ms")
        
    print_stats("Polling (GET /api/voter/current)", polls)
    print()
    print_stats("Voting (POST /vote)", votes)
    print()
    print("Peak RPS (burst window, first 10s):", peak_rps_burst)
    print("Peak RPS (sustained window):", peak_rps_sustained)
    print(f"Overall Success Rate: {overall_success_rate:.2f}%")
    print()
    
    # Verdict
    verdict_failed = []
    if overall_success_rate <= 99.0:
        verdict_failed.append(f"Success Rate ({overall_success_rate:.2f}% < 99%)")
    if max_p95_latency >= 1000:
        verdict_failed.append(f"p95 Latency ({max_p95_latency:.0f}ms > 1000ms)")
        
    if not verdict_failed:
        print("Verdict: Looks solid")
    else:
        print(f"Verdict: WARNING - Failed on {', '.join(verdict_failed)}")

if __name__ == "__main__":
    asyncio.run(main())
