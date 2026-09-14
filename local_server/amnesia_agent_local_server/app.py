"""FastAPI application for the reusable local agent server."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar, cast

from amnesia_agent_kernel import AgentError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from amnesia_agent_local_server.config import ConfigStore
from amnesia_agent_local_server.protocol import ConfigUpdate, ContentRequest, TurnRequest
from amnesia_agent_local_server.service import AgentService, TurnBusyError

API_PREFIX = "/v1"
T = TypeVar("T")


def create_app(
    config_store: ConfigStore | None = None,
    instance_id: str | None = None,
) -> FastAPI:
    """Create an application with a fresh server service."""
    app = FastAPI(title="Amnesia Agent Local Server", version="0.0.0-alpha.0")
    app.state.agent_service = AgentService(config_store, instance_id)
    app.state.uvicorn_server = None

    @app.get(f"{API_PREFIX}/health")
    async def health() -> dict[str, Any]:
        return cast(dict[str, Any], app.state.agent_service.health())

    @app.get(f"{API_PREFIX}/config")
    async def read_config() -> dict[str, Any]:
        return _call(lambda: app.state.agent_service.read_config())

    @app.put(f"{API_PREFIX}/config")
    async def update_config(update: ConfigUpdate) -> dict[str, Any]:
        return _call(lambda: app.state.agent_service.update_config(update))

    @app.post(f"{API_PREFIX}/config/reset")
    async def reset_config() -> dict[str, Any]:
        return _call(lambda: app.state.agent_service.reset_config())

    @app.post(f"{API_PREFIX}/turn")
    async def turn(request: Request, turn_request: TurnRequest) -> StreamingResponse:
        service: AgentService = app.state.agent_service
        if service.active:
            raise HTTPException(status_code=409, detail="Another turn is already active")

        async def stream() -> AsyncIterator[str]:
            events = service.stream_turn(turn_request.text)
            try:
                async for event in events:
                    if await request.is_disconnected():
                        break
                    yield _sse(event)
            finally:
                await events.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get(f"{API_PREFIX}/workspace/check")
    async def check_workspace() -> dict[str, bool]:
        return {"ok": _call(lambda: app.state.agent_service.check_workspace())}

    @app.post(f"{API_PREFIX}/workspace/setup-or-repair")
    async def setup_or_repair_workspace() -> dict[str, bool]:
        _call(lambda: app.state.agent_service.setup_or_repair_workspace())
        return {"ok": True}

    @app.post(f"{API_PREFIX}/workspace/create-or-reset")
    async def create_or_reset_workspace() -> dict[str, bool]:
        _call(lambda: app.state.agent_service.create_or_reset_workspace())
        return {"ok": True}

    @app.get(f"{API_PREFIX}/workspace/system-prompt")
    async def read_system_prompt() -> dict[str, str]:
        return _content_response(lambda: app.state.agent_service.read_system_prompt())

    @app.put(f"{API_PREFIX}/workspace/system-prompt")
    async def update_system_prompt(content: ContentRequest) -> dict[str, str]:
        return _content_response(
            lambda: app.state.agent_service.update_system_prompt(content.content)
        )

    @app.get(f"{API_PREFIX}/workspace/memory")
    async def read_memory() -> dict[str, str]:
        return _content_response(lambda: app.state.agent_service.read_memory())

    @app.put(f"{API_PREFIX}/workspace/memory")
    async def update_memory(content: ContentRequest) -> dict[str, str]:
        return _content_response(lambda: app.state.agent_service.update_memory(content.content))

    @app.get(f"{API_PREFIX}/workspace/history")
    async def list_history() -> dict[str, list[str]]:
        return {"dates": _call(lambda: app.state.agent_service.list_history())}

    @app.get(f"{API_PREFIX}/workspace/history/{{date}}")
    async def read_history(date: str) -> dict[str, Any]:
        return {"date": date, "messages": _call(lambda: app.state.agent_service.read_history(date))}

    @app.post(f"{API_PREFIX}/workspace/history/reset")
    async def reset_history() -> dict[str, bool]:
        _call(lambda: app.state.agent_service.reset_history())
        return {"reset": True}

    @app.post(f"{API_PREFIX}/shutdown")
    async def shutdown() -> dict[str, bool]:
        server = app.state.uvicorn_server
        if server is not None:
            server.should_exit = True
        return {"shutting_down": True}

    return app


def _call(function: Callable[[], T]) -> T:
    try:
        return function()
    except TurnBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (AgentError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _content_response(function: Callable[[], str]) -> dict[str, str]:
    return {"content": _call(function)}


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
