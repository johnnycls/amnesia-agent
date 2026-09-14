"""Workspace lifecycle and KernelSession read/update mirrors."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/workspace", tags=["workspace"])


class ContentRequest(BaseModel):
    """Text content for system-prompt or memory updates."""

    content: str
    workspace_path: str | None = None


class HistoryUpdate(BaseModel):
    """Body for ``update_history``; ``date`` defaults to today when omitted/null."""

    messages: list[Any]
    date: str | None = None
    workspace_path: str | None = None


class WorkspacePathBody(BaseModel):
    """Optional workspace path for lifecycle POSTs that otherwise have no body."""

    workspace_path: str | None = None


@router.get("/check")
def check_workspace(
    request: Request,
    workspace_path: Annotated[str | None, Query()] = None,
) -> dict[str, bool]:
    return {"ok": request.app.state.session.check_workspace(workspace_path)}


@router.post("/setup-or-repair")
def setup_or_repair_workspace(
    request: Request,
    body: WorkspacePathBody | None = None,
) -> dict[str, bool]:
    path = body.workspace_path if body is not None else None
    request.app.state.session.setup_or_repair_workspace(path)
    return {"ok": True}


@router.post("/create-or-reset")
def create_or_reset_workspace(
    request: Request,
    body: WorkspacePathBody | None = None,
) -> dict[str, bool]:
    path = body.workspace_path if body is not None else None
    request.app.state.session.create_or_reset_workspace(path)
    return {"ok": True}


@router.get("/system-prompt")
def read_system_prompt(
    request: Request,
    workspace_path: Annotated[str | None, Query()] = None,
) -> dict[str, str]:
    return {"content": request.app.state.session.read_system_prompt(workspace_path)}


@router.put("/system-prompt")
def update_system_prompt(body: ContentRequest, request: Request) -> dict[str, str]:
    return {
        "content": request.app.state.session.update_system_prompt(body.content, body.workspace_path)
    }


@router.get("/memory")
def read_memory(
    request: Request,
    workspace_path: Annotated[str | None, Query()] = None,
) -> dict[str, str]:
    return {"content": request.app.state.session.read_memory(workspace_path)}


@router.put("/memory")
def update_memory(body: ContentRequest, request: Request) -> dict[str, str]:
    return {"content": request.app.state.session.update_memory(body.content, body.workspace_path)}


@router.get("/history")
def list_history(
    request: Request,
    workspace_path: Annotated[str | None, Query()] = None,
) -> dict[str, list[str]]:
    return {"dates": request.app.state.session.list_history(workspace_path)}


@router.get("/history/{date}")
def read_history(
    date: str,
    request: Request,
    workspace_path: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return {
        "date": date,
        "messages": request.app.state.session.read_history(date, workspace_path),
    }


@router.put("/history")
def update_history(body: HistoryUpdate, request: Request) -> dict[str, Any]:
    request.app.state.session.update_history(body.messages, body.date, body.workspace_path)
    return {"messages": body.messages, "date": body.date}


@router.post("/history/reset")
def reset_history(
    request: Request,
    body: WorkspacePathBody | None = None,
) -> dict[str, bool]:
    path = body.workspace_path if body is not None else None
    request.app.state.session.reset_history(path)
    return {"reset": True}
