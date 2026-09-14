"""Turn streaming via SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from amnesia_agent_local_server.session import TurnBusyError
from amnesia_agent_local_server.sse import encode_sse

router = APIRouter(tags=["turn"])


class TurnRequest(BaseModel):
    """One user turn."""

    text: str = Field(min_length=1)


@router.post("/turn")
async def turn(turn_request: TurnRequest, request: Request) -> StreamingResponse:
    session = request.app.state.session
    if session.active_turn:
        raise TurnBusyError("Another turn is already active")

    async def stream() -> AsyncIterator[str]:
        events = session.stream_turn(turn_request.text)
        try:
            async for event in events:
                if await request.is_disconnected():
                    break
                yield encode_sse(event)
        finally:
            await events.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
