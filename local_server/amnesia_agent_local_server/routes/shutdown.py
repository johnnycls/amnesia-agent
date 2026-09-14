"""Graceful shutdown for desktop frontends."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["shutdown"])


@router.post("/shutdown")
def shutdown(request: Request) -> dict[str, bool]:
    server = request.app.state.uvicorn_server
    if server is not None:
        server.should_exit = True
    return {"shutting_down": True}
