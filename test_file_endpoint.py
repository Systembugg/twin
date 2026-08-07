import asyncio
import os
import httpx
from pathlib import Path
from twin.config import Settings
from twin.store.base import RunStatus
from twin.store.memory import InMemoryStore
from twin.runtime.api import create_app

async def test_file_download():
    # 1. Setup workspace and dummy file
    workspace_root = Path("C:/tmp/twin-workspaces")
    file_dir = workspace_root / "user_1" / "session_1"
    file_dir.mkdir(parents=True, exist_ok=True)
    
    test_file = file_dir / "report.docx"
    test_file.write_bytes(b"PK\x03\x04Dummy DOCX File Content for Unit Testing")

    # 2. Build app
    settings = Settings(workspace_root=str(workspace_root))
    store = InMemoryStore()
    
    async def mock_auth(authorization: str | None) -> str | None:
        return "user_1"

    app = create_app(settings=settings, store=store, redis=None, authenticate=mock_auth)

    # 3. Test endpoint using AsyncClient with ASGITransport
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Test download endpoint
        res = await client.get("/sessions/session_1/files/report.docx", headers={"Authorization": "Bearer token"})
        assert res.status_code == 200
        assert b"Dummy DOCX" in res.content

        # Test combined GET /runs/{run_id} response
        run = await store.create_run(user_id="user_1", session_id="session_1")
        await store.save_messages(user_id="user_1", run_id=run.id, messages=[{"role": "assistant", "content": "Here is your report"}])
        await store.set_status(user_id="user_1", run_id=run.id, status=RunStatus.SUCCEEDED)

        run_res = await client.get(f"/runs/{run.id}", headers={"Authorization": "Bearer token"})
        data = run_res.json()
        print(f"Combined JSON Response:\n{data}")
        assert data["text"] == "Here is your report"
        assert len(data["files"]) >= 1
        file_names = [f["name"] for f in data["files"]]
        assert "report.docx" in file_names
        print("SUCCESS: Combined Text + Files JSON Response TEST PASSED 100%!")

if __name__ == "__main__":
    asyncio.run(test_file_download())
