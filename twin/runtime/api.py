"""HTTP API.

`POST /runs` enqueues and returns immediately. It never waits for the run.
That single property is what makes 50+ concurrent users work: an agentic run
takes minutes and twenty API calls, so a web process that holds the request
open falls over around ten users no matter how fast the loop is.

Progress comes back over `GET /runs/{id}/events`, an SSE stream that replays
any events the client missed (`Last-Event-ID`) before switching to live.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from twin.config import Settings
from twin.errors import RateLimited
from twin.runtime.queue import EventBus, RunQueue
from twin.runtime.ratelimit import RateLimiter
from twin.store.base import RunStatus

log = logging.getLogger(__name__)

#: Events the client is guaranteed to see before the stream closes.
_TERMINAL_EVENTS = {"run_finished", "run_failed"}


class CreateRunRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=100_000)


class CreateRunResponse(BaseModel):
    run_id: str
    status: str


class FileInfo(BaseModel):
    name: str
    download_url: str


class RunView(BaseModel):
    run_id: str
    session_id: str
    status: str
    iterations: int
    spend_usd: float
    text: str | None = None
    files: list[FileInfo] = []
    error: str | None = None


def create_app(
    *,
    settings: Settings,
    store: Any,
    redis: Any,
    authenticate: Any,
    lifespan: Any = None,
) -> FastAPI:
    """`authenticate` maps an Authorization header to a user_id, or raises 401.

    Tenancy starts here and is carried explicitly from this point down. No
    handler reads a user ID from the request body.

    The caller owns `lifespan`, and must call `RunQueue(redis).ensure_group()`
    there. See `build_default_app` for the production wiring.
    """
    app = FastAPI(title="twin", version="0.1.0", lifespan=lifespan)
    queue = RunQueue(redis)
    bus = EventBus(redis)
    limiter = RateLimiter(redis=redis, quota=settings.quota)

    async def current_user(authorization: str | None = Header(default=None)) -> str:
        user_id = await authenticate(authorization)
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user_id

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        depth = (await queue.depth()) if redis else 0
        return {"ok": True, "queue_depth": depth}

    @app.get("/dashboard")
    @app.get("/")
    async def dashboard():
        from fastapi.responses import HTMLResponse
        from twin.runtime.dashboard_html import DASHBOARD_HTML
        return HTMLResponse(DASHBOARD_HTML)

    @app.post("/runs", response_model=CreateRunResponse, status_code=202)
    async def create_run(
        body: CreateRunRequest,
        user_id: str = Depends(current_user),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> CreateRunResponse:
        try:
            run = await store.create_run(
                user_id=user_id,
                session_id=body.session_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("create_run failed user=%s", user_id)
            raise HTTPException(status_code=500, detail="Could not create run") from exc

        # A replayed idempotency key returns the original run without
        # enqueuing a second one.
        if run.status is not RunStatus.QUEUED or run.iterations > 0:
            return CreateRunResponse(run_id=run.id, status=run.status.value)

        try:
            await limiter.admit(user_id, run.id)
        except RateLimited as exc:
            await store.set_status(
                user_id=user_id,
                run_id=run.id,
                status=RunStatus.CANCELLED,
                error=str(exc),
            )
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"Retry-After": str(int(exc.retry_after_s))},
            ) from exc

        if redis:
            await queue.enqueue(
                run_id=run.id,
                user_id=user_id,
                session_id=body.session_id,
                message=body.message,
            )
        else:
            from twin.runtime.local_worker import enqueue_local_run
            await enqueue_local_run(
                store=store,
                settings=settings,
                user_id=user_id,
                session_id=body.session_id,
                run_id=run.id,
                message=body.message,
            )
        return CreateRunResponse(run_id=run.id, status=RunStatus.QUEUED.value)

    @app.get("/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: str, user_id: str = Depends(current_user)) -> RunView:
        run = await store.get_run(user_id=user_id, run_id=run_id)
        # 404 rather than 403 for someone else's run: a 403 confirms the run
        # exists, which is itself a leak.
        if run is None:
            raise HTTPException(status_code=404, detail="No such run")
        text_out = ""
        if run.messages:
            last = run.messages[-1]
            if last.get("role") == "assistant":
                content = last.get("content")
                if isinstance(content, str):
                    text_out = content
                elif isinstance(content, list):
                    text_out = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")

        # Automatically list all generated workspace files for this session
        from twin.sandbox.local import _safe_component
        safe_user = _safe_component(user_id)
        safe_session = _safe_component(run.session_id)
        workspace_root = Path(settings.workspace_root).resolve()
        session_dir = workspace_root / safe_user / safe_session
        
        file_list: list[FileInfo] = []
        if session_dir.exists() and session_dir.is_dir():
            for f in sorted(session_dir.iterdir()):
                if f.is_file():
                    file_list.append(FileInfo(
                        name=f.name,
                        download_url=f"/sessions/{run.session_id}/files/{f.name}"
                    ))

        return RunView(
            run_id=run.id,
            session_id=run.session_id,
            status=run.status.value,
            iterations=run.iterations,
            spend_usd=run.spend_usd,
            text=text_out,
            files=file_list,
            error=run.error,
        )

    @app.get("/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        request: Request,
        user_id: str = Depends(current_user),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        run = await store.get_run(user_id=user_id, run_id=run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="No such run")

        after = _parse_seq(last_event_id)

        async def generate() -> AsyncIterator[str]:
            # Subscribe *before* replaying, so events produced during the
            # replay are buffered rather than lost in the gap.
            subscription = bus.subscribe(run_id)
            seen = after
            try:
                for event in await store.load_events(
                    user_id=user_id, run_id=run_id, after_seq=after
                ):
                    seen = max(seen, event.seq)
                    yield event.to_sse()
                    if event.type.value in _TERMINAL_EVENTS:
                        return

                async for event in subscription:
                    if await request.is_disconnected():
                        return
                    if event.seq <= seen:
                        continue  # already replayed
                    seen = event.seq
                    yield event.to_sse()
                    if event.type.value in _TERMINAL_EVENTS:
                        return
            except asyncio.CancelledError:
                raise
            finally:
                with contextlib.suppress(Exception):
                    await subscription.aclose()

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # nginx must not buffer SSE
            },
        )

    @app.get("/sessions/{session_id}/files/{filename}")
    async def get_session_file(
        session_id: str,
        filename: str,
        user_id: str = Depends(current_user),
    ):
        """Serves generated workspace files (.docx, .pdf, .png, .txt, .xlsx) securely."""
        from fastapi.responses import FileResponse
        from twin.sandbox.local import _safe_component

        safe_user = _safe_component(user_id)
        safe_session = _safe_component(session_id)
        safe_file = Path(filename).name

        workspace_root = Path(settings.workspace_root).resolve()
        file_path = (workspace_root / safe_user / safe_session / safe_file).resolve()

        if not file_path.exists() or file_path.is_dir():
            raise HTTPException(status_code=404, detail="File not found in workspace")

        # Security check: prevent directory traversal outside workspace
        user_root = (workspace_root / safe_user / safe_session).resolve()
        if not file_path.is_relative_to(user_root):
            raise HTTPException(status_code=403, detail="Access denied")

        return FileResponse(path=str(file_path), filename=safe_file)

    return app


def _parse_seq(value: str | None) -> int:
    try:
        return int(value) if value else 0
    except ValueError:
        return 0


class DeferredStore:
    """A `ConversationStore` whose pool is opened during lifespan startup.

    The app object is built before an event loop exists, so the pool cannot be
    created in the factory. Every method on the store protocol is async, so
    forwarding through `__getattr__` is sufficient — but only after `open()`
    has run, which is why an unopened access raises rather than silently
    connecting on a request path.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._store: Any = None

    async def open(self) -> None:
        from twin.store.postgres import PostgresStore

        self._store = await PostgresStore.connect(self._dsn)

    async def close(self) -> None:
        if self._store is not None:
            await self._store.close()
            self._store = None

    def __getattr__(self, name: str) -> Any:
        async def _call(*args: Any, **kwargs: Any) -> Any:
            if self._store is None:
                raise RuntimeError("store used before lifespan startup")
            return await getattr(self._store, name)(*args, **kwargs)

        return _call


def build_default_app() -> FastAPI:
    """`uvicorn twin.runtime.api:build_default_app --factory`."""
    import redis.asyncio as aioredis

    settings = Settings.from_env()
    if not settings.redis_url or not settings.database_url:
        raise SystemExit("TWIN_REDIS_URL and TWIN_DATABASE_URL are required")

    redis = aioredis.from_url(settings.redis_url)
    store = DeferredStore(settings.database_url)

    from twin.runtime.auth import authenticate_token

    async def authenticate(authorization: str | None) -> str | None:
        """Authenticate request using JWT token in Authorization header."""
        return authenticate_token(authorization)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await store.open()
        await RunQueue(redis).ensure_group()
        try:
            yield
        finally:
            await store.close()
            with contextlib.suppress(Exception):
                await redis.aclose()

    return create_app(
        settings=settings,
        store=store,
        redis=redis,
        authenticate=authenticate,
        lifespan=lifespan,
    )
