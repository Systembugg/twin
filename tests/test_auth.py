import time
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.runtime.api import create_app
from twin.runtime.auth import DEFAULT_TEST_SECRET, authenticate_token
from twin.store.memory import InMemoryStore


def make_token(
    user_id: str,
    secret: str = DEFAULT_TEST_SECRET,
    expires_in_s: int = 3600,
    alg: str = "HS256",
) -> str:
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in_s,
    }
    return jwt.encode(payload, secret, algorithm=alg)


def test_valid_token_returns_user_id():
    token = make_token("user_123")
    user_id = authenticate_token(f"Bearer {token}")
    assert user_id == "user_123"


def test_expired_token_returns_none():
    expired_token = make_token("user_123", expires_in_s=-10)
    user_id = authenticate_token(f"Bearer {expired_token}")
    assert user_id is None


def test_tampered_signature_returns_none():
    valid_token = make_token("user_123", secret="correct-secret-key")
    # Attempt to decode with wrong secret / tampered signature
    user_id = authenticate_token(f"Bearer {valid_token}", secret_or_key="wrong-secret-key")
    assert user_id is None


def test_missing_or_malformed_header_returns_none():
    assert authenticate_token(None) is None
    assert authenticate_token("") is None
    assert authenticate_token("InvalidHeader") is None
    assert authenticate_token("Basic dXNlcjpwYXNz") is None


@pytest.mark.asyncio
async def test_multi_tenant_user_a_cannot_access_user_b_run_returns_404():
    """Verify that User A accessing User B's run_id returns 404 (not 403 or 200)."""
    store = InMemoryStore()
    settings = Settings()

    async def mock_auth(authorization: str | None) -> str | None:
        return authenticate_token(authorization)

    app = create_app(
        settings=settings,
        store=store,
        redis=None,
        authenticate=mock_auth,
    )

    client = TestClient(app)

    # 1. Create a run as User B ("user_b")
    run_b = await store.create_run(user_id="user_b", session_id="sess_b")

    # 2. User A ("user_a") tries to request User B's run_id
    token_a = make_token("user_a")
    response = client.get(
        f"/runs/{run_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    # 3. Must be 404 Not Found (zero data leak, no 403 confirmation)
    assert response.status_code == 404
    assert response.json()["detail"] == "No such run"


@pytest.mark.asyncio
async def test_unauthorized_request_returns_401():
    store = InMemoryStore()
    settings = Settings()

    async def mock_auth(authorization: str | None) -> str | None:
        return authenticate_token(authorization)

    app = create_app(
        settings=settings,
        store=store,
        redis=None,
        authenticate=mock_auth,
    )

    client = TestClient(app)

    # Request without Authorization header
    response = client.post(
        "/runs",
        json={"session_id": "s1", "message": "hello"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"
