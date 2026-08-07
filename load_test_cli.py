"""Industry-Standard Multi-Tenant CLI Stress & Load Testing Harness.

Supports N concurrent users, custom prompt batches, latency p50/p95 benchmarking,
throughput (RPS), and error rate reporting.
"""

from __future__ import annotations

import argparse
import asyncio
import time
import httpx


PROMPT_POOL = [
    "what is market cap of apple and google",
    "write a python script to calculate primes up to 100 and save to primes.py",
    "write a friendly note in note.txt and list workspace directory",
    "explain how sliding window rate limiting works in redis",
    "search for recent developments in AI agent frameworks",
]


async def simulate_user_session(
    user_index: int,
    total_turns: int,
    server_url: str,
    results: list[dict],
    semaphore: asyncio.Semaphore,
):
    user_id = f"user_stress_{user_index}"
    session_id = f"session_stress_{user_index}"

    async with semaphore:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for turn in range(total_turns):
                prompt = PROMPT_POOL[turn % len(PROMPT_POOL)]
                start_t = time.time()

                try:
                    res = await client.post(
                        f"{server_url}/runs",
                        headers={"Authorization": f"Bearer user:{user_id}"},
                        json={"session_id": session_id, "message": prompt},
                    )
                    latency = round((time.time() - start_t) * 1000, 2)

                    if res.status_code == 202:
                        results.append(
                            {
                                "user_id": user_id,
                                "status": "SUCCEEDED",
                                "status_code": 202,
                                "latency_ms": latency,
                            }
                        )
                    else:
                        results.append(
                            {
                                "user_id": user_id,
                                "status": "FAILED",
                                "status_code": res.status_code,
                                "latency_ms": latency,
                            }
                        )
                except Exception as e:
                    latency = round((time.time() - start_t) * 1000, 2)
                    results.append(
                        {
                            "user_id": user_id,
                            "status": "ERROR",
                            "status_code": 0,
                            "error": str(e),
                            "latency_ms": latency,
                        }
                    )


async def run_industry_load_test(num_users: int, turns_per_user: int, concurrency: int, server_url: str):
    print("=" * 75)
    print("INDUSTRY-STANDARD MULTI-TENANT AGENT LOAD & STRESS HARNESS")
    print(f"Config: {num_users} Users | {turns_per_user} Turns/User | Max Concurrency: {concurrency}")
    print(f"Target Server: {server_url}")
    print("=" * 75 + "\n")

    results: list[dict] = []
    semaphore = asyncio.Semaphore(concurrency)

    start_time = time.time()

    tasks = [
        simulate_user_session(i + 1, turns_per_user, server_url, results, semaphore)
        for i in range(num_users)
    ]

    print(f"Spawning {num_users} concurrent user sessions...")
    await asyncio.gather(*tasks)

    total_duration = time.time() - start_time
    total_requests = len(results)
    successful = sum(1 for r in results if r["status"] == "SUCCEEDED")
    failed = sum(1 for r in results if r["status"] in ("FAILED", "ERROR"))
    latencies = [r["latency_ms"] for r in results]

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
    rps = round(total_requests / total_duration, 2)

    print("\n" + "=" * 75)
    print("INDUSTRY STRESS TEST BENCHMARK RESULTS")
    print("=" * 75)
    print(f" Total Test Duration    : {total_duration:.2f} s")
    print(f" Total Requests Sent    : {total_requests}")
    print(f" Successful (202 OK)    : {successful} ({successful/total_requests*100:.1f}%)")
    print(f" Failed / Rate-Limited  : {failed} ({failed/total_requests*100:.1f}%)")
    print(f" Throughput (RPS)       : {rps} req/sec")
    print(f" Latency p50            : {p50} ms")
    print(f" Latency p95            : {p95} ms")
    print(f" Latency p99            : {p99} ms")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Industry Standard Agent Load Tester")
    parser.add_argument("--users", type=int, default=10, help="Number of concurrent user profiles (0 limits!)")
    parser.add_argument("--turns", type=int, default=3, help="Turns per user session")
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent connections")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8000", help="Target API URL")
    args = parser.parse_args()

    asyncio.run(run_industry_load_test(args.users, args.turns, args.concurrency, args.url))


if __name__ == "__main__":
    main()
