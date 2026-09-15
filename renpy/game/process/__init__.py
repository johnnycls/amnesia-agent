"""Spawn, poll, and shut down the local_server sidecar."""

from process.lifecycle import (
    BUNDLED_SERVER_NAME,
    ServerProcess,
    bundled_server_path,
)

__all__ = ["BUNDLED_SERVER_NAME", "ServerProcess", "bundled_server_path"]
