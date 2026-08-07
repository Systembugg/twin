import argparse
import asyncio
import os
import time
from pathlib import Path
from dotenv import load_dotenv
import jwt
from httpx import ASGITransport, AsyncClient

load_dotenv()

from twin.config import Settings
from twin.runtime.api import create_app
from twin.runtime.auth import DEFAULT_TEST_SECRET, authenticate_token
from twin.store.memory import InMemoryStore


def make_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, DEFAULT_TEST_SECRET, algorithm="HS256")


async def run_single_user_load(client: AsyncClient, user_num: int, message: str):
    user_id = f"loadtest_user_{user_num:02d}"
    session_id = f"session_{user_num:02d}"
    token = make_token(user_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": f"idempotency_key_{user_num:02d}",
    }

    try:
        response = await client.post(
            "/runs",
            json={"session_id": session_id, "message": message},
            headers=headers,
        )
        if response.status_code == 202:
            data = response.json()
            return {
                "user_id": user_id,
                "run_id": data["run_id"],
                "status": data["status"],
                "success": True,
            }
        else:
            return {
                "user_id": user_id,
                "run_id": None,
                "status": f"HTTP_{response.status_code}",
                "success": False,
            }
    except Exception as e:
        return {
            "user_id": user_id,
            "run_id": None,
            "status": f"ERROR_{e}",
            "success": False,
        }


async def main():
    parser = argparse.ArgumentParser(description="Multi-user Load Tester")
    parser.add_argument("--users", type=int, default=10, help="Number of concurrent users")
    parser.add_argument("--message", type=str, default="create a file report.md with 5 bullet points about python")
    args = parser.parse_args()

    num_users = args.users
    print(f"==================================================")
    print(f"Starting Load Test with {num_users} Concurrent Users")
    print(f"==================================================\n")

    store = InMemoryStore()
    settings = Settings.from_env()

    async def mock_auth(authorization: str | None) -> str | None:
        return authenticate_token(authorization)

    app = create_app(
        settings=settings,
        store=store,
        redis=None,
        authenticate=mock_auth,
    )

    transport = ASGITransport(app=app)
    max_queue_depth = 0

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check initial healthz
        health_res = await client.get("/healthz")
        if health_res.status_code == 200:
            init_depth = health_res.json().get("queue_depth", 0)
            max_queue_depth = max(max_queue_depth, init_depth)
            print(f"Initial /healthz check -> Queue Depth: {init_depth}")

        start_time = time.time()

        # Spawn N concurrent POST /runs requests simultaneously
        tasks = [
            run_single_user_load(client, i + 1, args.message)
            for i in range(num_users)
        ]
        results = await asyncio.gather(*tasks)

        elapsed_time = time.time() - start_time

        # Audit healthz after burst
        health_res = await client.get("/healthz")
        if health_res.status_code == 200:
            burst_depth = health_res.json().get("queue_depth", 0)
            max_queue_depth = max(max_queue_depth, burst_depth)

    # Calculate metrics
    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded
    unique_users = len(set(r["user_id"] for r in results))

    print(f"\n==================================================")
    print(f"LOAD TEST SUMMARY RESULTS")
    print(f"==================================================")
    print(f"Total Concurrent Requests Sent: {num_users}")
    print(f"Distinct Users Authenticated:   {unique_users}")
    print(f"Successful 202 Enqueues:       {succeeded}")
    print(f"Failed Requests:               {failed}")
    print(f"Max Queue Depth Observed:       {max_queue_depth}")
    print(f"Burst Dispatch Time:           {elapsed_time:.4f}s")
    print(f"Average Request Latency:       {(elapsed_time / num_users) * 1000:.2f}ms per user")
    print(f"==================================================\n")

    assert succeeded == num_users, f"Expected {num_users} successful enqueues, got {succeeded}"
    print("SUCCESS: 100% of concurrent requests were admitted & enqueued without errors!")


if __name__ == "__main__":
    asyncio.run(main())
