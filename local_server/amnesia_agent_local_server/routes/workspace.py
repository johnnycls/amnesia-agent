"""Workspace lifecycle and KernelSession read/update mirrors."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/workspace", tags=["workspace"])


class ContentRequest(BaseModel):
    """Text content for system-prompt or memory updates."""

    content: str


class HistoryUpdate(BaseModel):
    """Body for ``update_history``; ``date`` defaults to today when omitted/null."""

    messages: list[Any]
    date: str | None = None


@router.get("/check")
def check_workspace(request: Request) -> dict[str, bool]:
    return {"ok": request.app.state.session.check_workspace()}


@router.post("/setup-or-repair")
def setup_or_repair_workspace(request: Request) -> dict[str, bool]:
    request.app.state.session.setup_or_repair_workspace()
    return {"ok": True}


@router.post("/create-or-reset")
def create_or_reset_workspace(request: Request) -> dict[str, bool]:
    request.app.state.session.create_or_reset_workspace()
    return {"ok": True}


@router.get("/system-prompt")
def read_system_prompt(request: Request) -> dict[str, str]:
    return {"content": request.app.state.session.read_system_prompt()}


@router.put("/system-prompt")
def update_system_prompt(body: ContentRequest, request: Request) -> dict[str, str]:
    return {"content": request.app.state.session.update_system_prompt(body.content)}


@router.get("/memory")
def read_memory(request: Request) -> dict[str, str]:
    return {"content": request.app.state.session.read_memory()}


@router.put("/memory")
def update_memory(body: ContentRequest, request: Request) -> dict[str, str]:
    return {"content": request.app.state.session.update_memory(body.content)}


@router.get("/history")
def list_history(request: Request) -> dict[str, list[str]]:
    return {"dates": request.app.state.session.list_history()}


@router.get("/history/{date}")
def read_history(date: str, request: Request) -> dict[str, Any]:
    return {"date": date, "messages": request.app.state.session.read_history(date)}


@router.put("/history")
def update_history(body: HistoryUpdate, request: Request) -> dict[str, Any]:
    request.app.state.session.update_history(body.messages, body.date)
    return {"messages": body.messages, "date": body.date}


@router.post("/history/reset")
def reset_history(request: Request) -> dict[str, bool]:
    request.app.state.session.reset_history()
    return {"reset": True}
