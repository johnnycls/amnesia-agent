"""Thin HTTP routers for the local server."""

from amnesia_agent_local_server.routes import config, health, shutdown, turn, workspace

__all__ = ["config", "health", "shutdown", "turn", "workspace"]
