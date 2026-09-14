"""Graceful shutdown for desktop frontends."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["shutdown"])


@router.post("/shutdown")
async def shutdown(request: Request) -> dict[str, bool]:
    server = request.app.state.uvicorn_server
    if server is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Shutdown unavailable: server was not started via the official "
                "amnesia-agent-local-server entrypoint"
            ),
        )
    await request.app.state.session.cancel_active_turn()
    server.should_exit = True
    return {"shutting_down": True}
