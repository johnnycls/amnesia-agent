"""Thin HTTP routers for the server."""

from amnesia_agent_server.routes import config, health, shutdown, turn, workspace

__all__ = ["config", "health", "shutdown", "turn", "workspace"]
