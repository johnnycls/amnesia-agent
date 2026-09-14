"""Turn streaming via SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from amnesia_agent_local_server.sse import encode_sse

router = APIRouter(tags=["turn"])


class TurnRequest(BaseModel):
    """One user turn."""

    text: str = Field(min_length=1)
    response_format: dict[str, Any] | None = None


@router.post("/turn")
async def turn(turn_request: TurnRequest, request: Request) -> StreamingResponse:
    session = request.app.state.session
    # Acquire busy synchronously so TurnBusyError maps to HTTP 409 before SSE.
    events = session.start_turn(
        turn_request.text,
        response_format=turn_request.response_format,
    )

    async def stream() -> AsyncIterator[str]:
        async with aclosing(events):
            async for event in events:
                if await request.is_disconnected():
                    break
                yield encode_sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
