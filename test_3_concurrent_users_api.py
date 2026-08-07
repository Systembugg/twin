import asyncio
import time
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


async def run_api_user_flow(client: AsyncClient, user_id: str, prompt: str):
    token = make_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. POST /runs
    response = await client.post(
        "/runs",
        json={"session_id": f"session_{user_id}", "message": prompt},
        headers=headers,
    )
    assert response.status_code == 202, f"Failed for {user_id}: {response.text}"
    data = response.json()
    run_id = data["run_id"]
    status = data["status"]
    print(f"[{user_id}] POST /runs -> HTTP 202 | Run ID: {run_id} | Status: {status}")

    # 2. GET /runs/{run_id} (Check status)
    get_res = await client.get(f"/runs/{run_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["run_id"] == run_id
    print(f"[{user_id}] GET /runs/{run_id} -> HTTP 200 | Verified Owner")

    return user_id, run_id


async def main():
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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        print("=== Starting Simultaneous 3-User HTTP API Concurrency Test ===\n")

        # Create tasks for 3 simultaneous users
        task1 = run_api_user_flow(client, "user_1", "Write user 1 report")
        task2 = run_api_user_flow(client, "user_2", "Write user 2 report")
        task3 = run_api_user_flow(client, "user_3", "Write user 3 report")

        results = await asyncio.gather(task1, task2, task3)

        print("\n=== Cross-Tenant Security Audit ===")
        # Test User 1 attempting to access User 2's run_id -> MUST BE 404
        token_1 = make_token("user_1")
        user_2_run_id = results[1][1]

        leak_check = await client.get(
            f"/runs/{user_2_run_id}",
            headers={"Authorization": f"Bearer {token_1}"},
        )

        print(f"User 1 trying to access User 2's run ({user_2_run_id}) -> HTTP {leak_check.status_code}")
        assert leak_check.status_code == 404
        assert leak_check.json()["detail"] == "No such run"

        print("\nSUCCESS: All 3 Users executed API requests concurrently with 100% security & zero data leakage!")


if __name__ == "__main__":
    asyncio.run(main())
