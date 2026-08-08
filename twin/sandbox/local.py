"""Local filesystem sandbox: a scoped directory with a hard containment check.

This is *not* a security boundary against hostile code — a shell command can
still read anything the worker process can. It is a correctness boundary for a
trusted-but-fallible model, and the development stand-in for a real container.

Ship the container before you ship untrusted multi-tenant execution. The
interface is identical, so that swap is a config change.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
from pathlib import Path

from twin.errors import PathNotAllowed, SandboxError
from twin.sandbox.base import ExecResult

log = logging.getLogger(__name__)

_MAX_CAPTURE = 200_000  # bytes of stdout/stderr retained per exec


class LocalSandbox:
    """Confines all file access below ``root``.

    Containment is checked on the *fully resolved* path, so symlinks pointing
    outside the root are rejected rather than followed. `Path.resolve()` is
    what makes this correct; a string prefix check is not sufficient.
    """

    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root.resolve()
        self.session_id = session_id
        self._closed = False

    # -- path handling ------------------------------------------------------

    def resolve(self, path: str) -> Path:
        """Resolve a model-supplied path, or raise `PathNotAllowed`."""
        clean_path = str(path).lstrip("/\\")
        candidate = Path(clean_path)
        if candidate.is_absolute() and candidate.drive:
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()

        # `is_relative_to` compares resolved paths, so `..` and symlink escapes
        # are both caught here.
        if resolved != self.root and not resolved.is_relative_to(self.root):
            log.warning(
                "path escape rejected session=%s requested=%r resolved=%s",
                self.session_id,
                path,
                resolved,
            )
            raise PathNotAllowed(
                f"Path {path!r} is outside the workspace. "
                f"Use paths relative to the workspace root."
            )
        return resolved

    def relative(self, resolved: Path) -> str:
        """Path as the model should see it — never leak the host layout."""
        try:
            return str(resolved.relative_to(self.root)) or "."
        except ValueError:
            return str(resolved)

    # -- Sandbox protocol ---------------------------------------------------

    async def read_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.exists():
            raise SandboxError(f"No such file: {self.relative(target)}")
        if target.is_dir():
            raise SandboxError(f"{self.relative(target)} is a directory, not a file.")
        try:
            return await asyncio.to_thread(target.read_text, "utf-8", "replace")
        except OSError as exc:
            raise SandboxError(f"Could not read {self.relative(target)}: {exc}") from exc

    async def write_file(self, path: str, content: str) -> int:
        target = self.resolve(path)
        try:
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_text, content, "utf-8")
        except OSError as exc:
            raise SandboxError(f"Could not write {self.relative(target)}: {exc}") from exc
        return len(content.encode("utf-8"))

    async def list_dir(self, path: str = ".") -> list[str]:
        target = self.resolve(path)
        if not target.is_dir():
            raise SandboxError(f"{self.relative(target)} is not a directory.")
        entries = await asyncio.to_thread(lambda: sorted(os.listdir(target)))
        out = []
        for name in entries:
            child = target / name
            out.append(f"{name}/" if child.is_dir() else name)
        return out

    async def exec(self, command: str, timeout_s: float) -> ExecResult:
        if self._closed:
            raise SandboxError("Sandbox is closed.")

        # Inherit environment so Windows DNS/Winsock works, but scrub credentials
        env = os.environ.copy()
        for key in list(env.keys()):
            if "API_KEY" in key or key.startswith("TWIN_") or "TOKEN" in key or "SECRET" in key:
                del env[key]
                
        env["HOME"] = str(self.root)
        env["TWIN_SESSION_ID"] = self.session_id

        kwargs: dict[str, Any] = {
            "cwd": str(self.root),
            "env": env,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                **kwargs,
            )
        except OSError as exc:
            raise SandboxError(f"Could not start command: {exc}") from exc

        truncated = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            _kill_group(proc)
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {timeout_s:.0f}s and was killed.",
                timed_out=True,
            )

        if len(stdout_b) > _MAX_CAPTURE:
            stdout_b, truncated = stdout_b[:_MAX_CAPTURE], True
        if len(stderr_b) > _MAX_CAPTURE:
            stderr_b, truncated = stderr_b[:_MAX_CAPTURE], True

        return ExecResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_b.decode("utf-8", "replace"),
            stderr=stderr_b.decode("utf-8", "replace"),
            truncated=truncated,
        )

    async def close(self) -> None:
        self._closed = True


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    """Kill process group cross-platform on Linux and Windows."""
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid") and hasattr(signal, "SIGKILL"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


class LocalSandboxFactory:
    """Creates one directory per session under ``workspace_root``.

    Directories are namespaced by ``user_id`` so that a leaked or guessed
    session ID still cannot reach another tenant's files.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    async def acquire(self, *, user_id: str, session_id: str) -> LocalSandbox:
        safe_user = _safe_component(user_id)
        safe_session = _safe_component(session_id)
        root = self.workspace_root / safe_user / safe_session
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        return LocalSandbox(root=root, session_id=session_id)

    async def destroy(self, *, user_id: str, session_id: str) -> None:
        root = self.workspace_root / _safe_component(user_id) / _safe_component(session_id)
        if root.exists():
            await asyncio.to_thread(shutil.rmtree, root, True)


def _safe_component(value: str) -> str:
    """Reduce an identifier to something that cannot traverse or collide."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in value)
    if not cleaned or cleaned in (".", ".."):
        raise PathNotAllowed(f"Unusable identifier: {value!r}")
    return cleaned[:128]
