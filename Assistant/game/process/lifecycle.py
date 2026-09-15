"""Own the local_server child process (bundled sidecar or python -m)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from typing import Any

from api.client import ApiError, Client

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]

BUNDLED_SERVER_NAME = (
    "amnesia-agent-local-server.exe"
    if sys.platform == "win32"
    else "amnesia-agent-local-server"
)


def bundled_server_path() -> str | None:
    """Return game/server/<name> when the CI-built sidecar is present."""
    if renpy is None:
        return None
    config = getattr(renpy, "config", None)
    gamedir = getattr(config, "gamedir", None)
    if gamedir is None:
        return None
    candidate = os.path.join(os.fspath(gamedir), "server", BUNDLED_SERVER_NAME)
    return candidate if os.path.isfile(candidate) else None


class ServerProcess:
    """Start local_server, verify instance_id, request /v1/shutdown on stop."""

    def __init__(
        self,
        client: Client,
        python_command: str | None = None,
        startup_timeout: float = 15.0,
    ) -> None:
        self.client = client
        self.python_command = python_command or os.environ.get(
            "AMNESIA_AGENT_PYTHON", "python"
        )
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen[Any] | None = None
        self.instance_id: str | None = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.instance_id = uuid.uuid4().hex
        bundled = bundled_server_path()
        server_args = [
            "--host",
            self.client.host,
            "--port",
            str(self.client.port),
            "--instance-id",
            self.instance_id,
        ]
        command = (
            [bundled, *server_args]
            if bundled
            else [self.python_command, "-m", "amnesia_agent_local_server", *server_args]
        )
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except OSError as error:
            raise ApiError(f"Cannot start local server: {error}") from error

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ApiError("Local server exited before becoming ready")
            try:
                health = self.client.health(timeout=0.5)
            except ApiError:
                time.sleep(0.1)
                continue
            if health.get("instance_id") != self.instance_id:
                self.stop()
                raise ApiError(
                    f"Port {self.client.port} is already occupied by another "
                    "local server"
                )
            return
        self.stop()
        raise ApiError(
            f"Local server did not become ready on port {self.client.port}"
        )

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            try:
                self.client.request_json("POST", "/v1/shutdown", timeout=1.0)
            except ApiError:
                pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
