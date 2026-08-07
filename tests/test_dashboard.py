import pytest
from fastapi.testclient import TestClient
from twin.runtime.api import create_app
from twin.config import Settings


def test_dashboard_endpoint_returns_200_html():
    settings = Settings.from_env()

    async def mock_auth(token):
        return "user_123"

    app = create_app(
        settings=settings,
        store=None,
        redis=None,
        authenticate=mock_auth,
    )
    client = TestClient(app)

    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "Twin Mission Control" in res_dash.text
    assert "text/html" in res_dash.headers["content-type"]

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Multi-User Session Stress Tester" in res_root.text
