"""Turn streaming via SSE."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from amnesia_agent_local_server.constants import SSE_HEARTBEAT_SECONDS
from amnesia_agent_local_server.sse import encode_sse

# Empty path "" (not "/") so mount is /v1/turn without a trailing slash.
router = APIRouter(prefix="/turn", tags=["turn"])


class TurnRequest(BaseModel):
    """One user turn."""

    text: str = Field(min_length=1)
    response_format: dict[str, Any] | None = None
    workspace_path: str | None = None
    system_prompt_prefix: str = ""


@router.post("")
async def turn(turn_request: TurnRequest, request: Request) -> StreamingResponse:
    session = request.app.state.session
    # Acquire busy synchronously so TurnBusyError maps to HTTP 409 before SSE.
    events = session.start_turn(
        turn_request.text,
        response_format=turn_request.response_format,
        workspace_path=turn_request.workspace_path,
        system_prompt_prefix=turn_request.system_prompt_prefix,
    )

    async def stream() -> AsyncIterator[str]:
        async with aclosing(events):
            async for frame in stream_sse(
                events,
                request,
                heartbeat_seconds=SSE_HEARTBEAT_SECONDS,
            ):
                yield frame

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def stream_sse(
    events: AsyncIterator[dict[str, Any]],
    request: Request,
    *,
    heartbeat_seconds: float,
) -> AsyncIterator[str]:
    """Encode events while keeping quiet SSE connections alive."""
    async def next_event_value() -> dict[str, Any]:
        return await events.__anext__()

    next_event: asyncio.Task[dict[str, Any]] | None = asyncio.create_task(next_event_value())
    try:
        while next_event is not None:
            done, _pending = await asyncio.wait({next_event}, timeout=heartbeat_seconds)
            if not done:
                if await request.is_disconnected():
                    return
                yield ": heartbeat\n\n"
                continue
            try:
                event = next_event.result()
            except StopAsyncIteration:
                return
            if await request.is_disconnected():
                return
            yield encode_sse(event)
            next_event = asyncio.create_task(next_event_value())
    finally:
        if next_event is not None and not next_event.done():
            next_event.cancel()
        if next_event is not None:
            await asyncio.gather(next_event, return_exceptions=True)
