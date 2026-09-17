"""FastAPI assembly: routers, exception handlers, and server security modes."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from amnesia_agent_kernel import AgentError, ConfigError, WorkspaceError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from amnesia_agent_server.auth import RemoteAuthMiddleware
from amnesia_agent_server.browser_origin import BrowserOriginMiddleware
from amnesia_agent_server.config import ConfigStore
from amnesia_agent_server.constants import API_PREFIX
from amnesia_agent_server.pairing import DeviceTokenStore, PairingManager
from amnesia_agent_server.routes import config, health, pair, shutdown, turn, workspace
from amnesia_agent_server.session import SessionManager, TurnBusyError


def create_app(
    config_store: ConfigStore | None = None,
    instance_id: str | None = None,
    *,
    remote: bool = False,
    public_url: str | None = None,
    pairing_manager: PairingManager | None = None,
    workspace_root: str | None = None,
) -> FastAPI:
    """Create a local or authenticated remote application.

    Local mode intentionally preserves the original loopback trust model. Remote
    mode requires a pairing manager and bearer-authenticates every API route
    except the one-time ``/v1/pair`` exchange.
    """
    store = config_store or ConfigStore()
    device_tokens = DeviceTokenStore(store.root / "device-tokens.json")
    if remote and pairing_manager is None:
        if public_url is None:
            raise ValueError("Remote mode requires public_url")
        pairing_manager = PairingManager(public_url, device_tokens)
    app = FastAPI(
        title="Amnesia Agent Server",
        version="0.0.0-alpha.0",
        docs_url=None if remote else "/docs",
        redoc_url=None if remote else "/redoc",
        openapi_url=None if remote else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^https?://(?:localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d+)?$"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Install after CORS so this middleware is the outer request guard. CORS
    # controls browser response access; this rejects disallowed origins before
    # any endpoint, including state-changing endpoints, is executed.
    app.add_middleware(BrowserOriginMiddleware)
    if remote:
        assert pairing_manager is not None
        app.add_middleware(RemoteAuthMiddleware, device_tokens=device_tokens)
    if remote and workspace_root is None:
        workspace_root = str(Path.home() / ".amnesia-agent")
    app.state.session = SessionManager(store, instance_id, workspace_root=workspace_root)
    app.state.remote = remote
    app.state.pairing_manager = pairing_manager
    app.state.pairing_task = None
    app.state.uvicorn_server = None

    # Version prefix only; each route module owns its resource prefix.
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(config.router, prefix=API_PREFIX)
    app.include_router(workspace.router, prefix=API_PREFIX)
    app.include_router(turn.router, prefix=API_PREFIX)
    app.include_router(shutdown.router, prefix=API_PREFIX)
    if remote:
        app.include_router(pair.router, prefix=API_PREFIX)

    if remote:
        assert pairing_manager is not None

        @app.on_event("startup")
        async def start_pairing_rotation() -> None:
            app.state.pairing_task = asyncio.create_task(
                _pairing_rotation(pairing_manager)
            )

        @app.on_event("shutdown")
        async def stop_pairing_rotation() -> None:
            task = app.state.pairing_task
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    _install_exception_handlers(app)
    return app


async def _pairing_rotation(manager: PairingManager) -> None:
    """Print a new pairing QR whenever the active code expires."""
    while True:
        payload = manager.current_payload()
        if manager.on_rotate is None:
            manager.print_payload(payload)
        await asyncio.sleep(max(1, int(manager.expiry() - time.time())))


def _install_exception_handlers(app: FastAPI) -> None:
    """Map expected failures to HTTP status + JSON ``detail`` bodies."""

    @app.exception_handler(TurnBusyError)
    async def turn_busy_handler(_request: Request, exc: TurnBusyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ConfigError)
    async def config_error_handler(_request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_error_detail(exc))

    @app.exception_handler(WorkspaceError)
    async def workspace_error_handler(_request: Request, exc: WorkspaceError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_error_detail(exc))

    @app.exception_handler(AgentError)
    async def agent_error_handler(_request: Request, exc: AgentError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_error_detail(exc))

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(OSError)
    async def os_error_handler(_request: Request, exc: OSError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})


def _error_detail(exc: AgentError) -> dict[str, Any]:
    detail: dict[str, Any] = {"detail": str(exc)}
    if exc.path is not None:
        detail["path"] = exc.path
    return detail
