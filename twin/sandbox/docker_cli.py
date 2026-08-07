"""Docker CLI Sandbox Factory.

Spins up a real, isolated Alpine Linux container for every single run.
Uses standard subprocesses to call the local `docker` CLI, so it requires no
extra Python dependencies and is 100% free. Perfect for demonstrating true
isolation without paying for cloud sandboxes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from twin.errors import SandboxError
from twin.sandbox.base import ExecResult

log = logging.getLogger(__name__)

_MAX_CAPTURE = 200_000  # bytes of stdout/stderr retained per exec


class DockerCLISandbox:
    """An isolated filesystem and process namespace inside an Alpine container."""

    def __init__(self, container_name: str, session_id: str) -> None:
        self.container_name = container_name
        self.session_id = session_id
        self._closed = False

    async def read_file(self, path: str) -> str:
        cmd = f'docker exec {self.container_name} cat "{path}"'
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise SandboxError(f"Could not read {path}: {stderr.decode('utf-8', 'replace')}")
        return stdout.decode("utf-8", "replace")

    async def write_file(self, path: str, content: str) -> int:
        # First ensure the directory exists
        cmd_mkdir = f'docker exec {self.container_name} sh -c \'mkdir -p "$(dirname "{path}")"\''
        proc_mkdir = await asyncio.create_subprocess_shell(
            cmd_mkdir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc_mkdir.communicate()

        # Write the file via stdin pipe
        cmd_write = f'docker exec -i {self.container_name} sh -c \'cat > "{path}"\''
        proc = await asyncio.create_subprocess_shell(
            cmd_write,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=content.encode("utf-8"))
        if proc.returncode != 0:
            raise SandboxError(f"Could not write {path}: {stderr.decode('utf-8', 'replace')}")
        return len(content.encode("utf-8"))

    async def list_dir(self, path: str = ".") -> list[str]:
        cmd = f'docker exec {self.container_name} ls -p "{path}"'
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            if "No such file or directory" in stderr.decode():
                raise SandboxError(f"{path} is not a directory.")
            raise SandboxError(f"Could not list {path}: {stderr.decode('utf-8', 'replace')}")
        
        entries = stdout.decode("utf-8", "replace").strip().split("\n")
        return [e for e in entries if e]

    async def exec(self, command: str, timeout_s: float) -> ExecResult:
        if self._closed:
            raise SandboxError("Sandbox is closed.")

        # Escape single quotes in the command to pass safely to sh -c
        safe_command = command.replace("'", "'\\''")
        cmd = f"docker exec -i {self.container_name} sh -c '{safe_command}'"

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise SandboxError(f"Could not start command: {exc}") from exc

        truncated = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()
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
        if not self._closed:
            self._closed = True
            cmd = f'docker rm -f {self.container_name}'
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()


class DockerCLISandboxFactory:
    """Spawns one Alpine container per session via the local Docker CLI."""

    async def acquire(self, *, user_id: str, session_id: str) -> DockerCLISandbox:
        safe_user = "".join(c if c.isalnum() else "_" for c in user_id)[:30]
        safe_session = "".join(c if c.isalnum() else "_" for c in session_id)[:30]
        container_name = f"twin_{safe_user}_{safe_session}"
        
        # Start a lightweight alpine container that just sleeps forever
        cmd = f'docker run -d --rm --name {container_name} -w /workspace alpine tail -f /dev/null'
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            err_msg = stderr.decode('utf-8', 'replace')
            # If the container already exists from a previous run crash, kill it and retry
            if "already in use" in err_msg:
                log.warning(f"Container {container_name} already exists. Removing and retrying.")
                await asyncio.create_subprocess_shell(f'docker rm -f {container_name}').communicate()
                proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise SandboxError(f"Failed to start docker container after retry: {stderr.decode('utf-8', 'replace')}")
            else:
                raise SandboxError(f"Failed to start docker container: {err_msg}. Is Docker installed and running?")
            
        log.info(f"Acquired Docker Sandbox: {container_name}")
        return DockerCLISandbox(container_name=container_name, session_id=session_id)
