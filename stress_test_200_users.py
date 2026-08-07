"""200-User Enterprise Rate Limiter & Queue Stress Test with Live Activity Stream.

Simulates 200 simultaneous users submitting prompts to the Central Twin Server
without opening 200 terminal windows!

Displays:
1. Live per-user activity stream (Enqueued, Dequeued, Completed, Rate Limited)
2. Real-time aggregate statistics table
"""

from __future__ import annotations

import argparse
import asyncio
import time
import httpx


def log_event(user_id: str, status: str, detail: str = ""):
    ts = time.strftime("%H:%M:%S")
    detail_str = f" - {detail}" if detail else ""
    print(f"[{ts}] [{user_id.upper()}] [{status}]{detail_str}")


async def run_single_user_test(
    client: httpx.AsyncClient,
    server_url: str,
    user_num: int,
    stats: dict[str, int],
    lock: asyncio.Lock,
):
    user_id = f"user_{user_num}"
    session_id = f"stress_session_{user_num}"
    headers = {"Authorization": f"Bearer {user_id}"}
    prompt = f"Hello! I am user_{user_num}. Please greet me by username user_{user_num} in 5 words."

    try:
        res = await client.post(
            f"{server_url}/runs",
            headers=headers,
            json={"session_id": session_id, "message": prompt},
        )

        async with lock:
            if res.status_code == 202:
                stats["admitted"] += 1
                run_id = res.json()["run_id"]
                log_event(user_id, "ENQUEUED", f"Run {run_id[:12]}... placed in Queue")
            elif res.status_code == 429:
                stats["rate_limited"] += 1
                log_event(user_id, "RATE_LIMITED", "429 Quota Exceeded - Blocked by Rate Limiter")
                return
            else:
                stats["errors"] += 1
                log_event(user_id, "HTTP_ERROR", f"Status {res.status_code}")
                return

        # Poll for completion if admitted
        start_t = time.time()
        last_status = "ENQUEUED"
        while time.time() - start_t < 120.0:
            await asyncio.sleep(0.5)
            r = await client.get(f"{server_url}/runs/{run_id}", headers=headers)
            if r.status_code == 200:
                run_info = r.json()
                st = run_info["status"].upper()

                if st != last_status:
                    last_status = st
                    if st == "RUNNING":
                        log_event(user_id, "DEQUEUED", f"Worker dequeued run {run_id[:12]}... - Processing on GPU")

                if st == "SUCCEEDED":
                    async with lock:
                        stats["completed"] += 1
                    turns = run_info.get("iterations", 1)
                    duration = time.time() - start_t
                    reply_text = run_info.get("text", "").strip().replace("\n", " ")
                    log_event(user_id, "FINISHED", f"[{duration:.1f}s] Response: {reply_text}")
                    break
                elif st in ("FAILED", "CANCELLED"):
                    async with lock:
                        stats["failed"] += 1
                    err_msg = run_info.get("error", "Execution failed")
                    log_event(user_id, "FAILED", f"Run failed: {err_msg}")
                    break

    except Exception as exc:
        async with lock:
            stats["errors"] += 1
        log_event(user_id, "EXCEPTION", f"{type(exc).__name__}: {exc}")


async def print_final_dashboard(stats: dict[str, int], total_users: int, start_time: float):
    print("\n" + "=" * 70)
    print("FINAL 200-USER ENTERPRISE STRESS TEST SUMMARY")
    print("=" * 70)
    print(f"Total Concurrent Users Fired : {total_users}")
    print(f"Total Test Duration          : {time.time() - start_time:.2f}s")
    print("-" * 70)
    print(f"✅ Admitted & Enqueued into Queue : {stats['admitted']}")
    print(f"⚠️ Blocked by Rate Limiter (429)  : {stats['rate_limited']}")
    print(f"🎉 Worker Completed Jobs         : {stats['completed']}")
    print(f"❌ Failed / Errors                : {stats['failed'] + stats['errors']}")
    print("-" * 70)
    print(f"Pass Rate (Admitted)              : {(stats['admitted'] / total_users) * 100:.1f}%")
    print(f"Queue System Success Rate        : {(stats['completed'] / max(1, stats['admitted'])) * 100:.1f}%")
    print("=" * 70 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="200-User Enterprise Rate Limiter Stress Test")
    parser.add_argument("--users", type=int, default=200, help="Number of concurrent users")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8000", help="Server URL")
    args = parser.parse_args()

    total_users = args.users
    server_url = args.url

    print("=" * 75)
    print(f"🚀 INITIALIZING 200-USER STRESS TEST AGAINST {server_url}")
    print("Streaming live per-user activity (QUEUED, DEQUEUED, FINISHED, RATE_LIMITED)...")
    print("=" * 75 + "\n")

    stats = {
        "admitted": 0,
        "rate_limited": 0,
        "completed": 0,
        "failed": 0,
        "errors": 0,
    }
    lock = asyncio.Lock()
    start_time = time.time()

    limits = httpx.Limits(max_keepalive_connections=50, max_connections=300)
    async with httpx.AsyncClient(timeout=45.0, limits=limits) as client:
        try:
            h = await client.get(f"{server_url}/healthz")
            if h.status_code != 200:
                print("❌ Central Server is not running! Start run_dashboard_server.py first.")
                return
        except Exception:
            print("❌ Cannot connect to Central Server at http://127.0.0.1:8000!")
            print("👉 Start: python run_dashboard_server.py in another terminal.")
            return

        # Fire all 200 user tasks simultaneously
        tasks = [
            run_single_user_test(client, server_url, i, stats, lock)
            for i in range(1, total_users + 1)
        ]

        await asyncio.gather(*tasks, return_exceptions=True)
        await print_final_dashboard(stats, total_users, start_time)


if __name__ == "__main__":
    asyncio.run(main())
