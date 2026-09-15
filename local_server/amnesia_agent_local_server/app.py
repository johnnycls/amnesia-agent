"""FastAPI assembly: routers, exception handlers, loopback app factory."""

from __future__ import annotations

from typing import Any

from amnesia_agent_kernel import AgentError, ConfigError, WorkspaceError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from amnesia_agent_local_server.config import ConfigStore
from amnesia_agent_local_server.constants import API_PREFIX
from amnesia_agent_local_server.routes import config, health, shutdown, turn, workspace
from amnesia_agent_local_server.session import SessionManager, TurnBusyError


def create_app(
    config_store: ConfigStore | None = None,
    instance_id: str | None = None,
) -> FastAPI:
    """Create an application with one ``SessionManager`` and versioned routers."""
    app = FastAPI(title="Amnesia Agent Local Server", version="0.0.0-alpha.0")
    app.state.session = SessionManager(config_store, instance_id)
    app.state.uvicorn_server = None

    # Version prefix only; each route module owns its resource prefix.
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(config.router, prefix=API_PREFIX)
    app.include_router(workspace.router, prefix=API_PREFIX)
    app.include_router(turn.router, prefix=API_PREFIX)
    app.include_router(shutdown.router, prefix=API_PREFIX)

    _install_exception_handlers(app)
    return app


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
