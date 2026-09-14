"""Configuration CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["config"])


class ConfigUpdate(BaseModel):
    """Partial config update; omitted values retain their current values."""

    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    provider_params: dict[str, Any] | None = None
    command_timeout_seconds: float | int | None = None
    max_command_output_bytes: int | None = None
    max_context_message_chars: int | None = None


@router.get("/config")
def read_config(request: Request) -> dict[str, Any]:
    return request.app.state.session.read_config()  # type: ignore[no-any-return]


@router.put("/config")
def update_config(update: ConfigUpdate, request: Request) -> dict[str, Any]:
    raw_fields = getattr(update, "model_fields_set", None)
    if raw_fields is None:
        raw_fields = getattr(update, "__fields_set__", set())
    fields = {name: getattr(update, name) for name in set(raw_fields or ())}
    return request.app.state.session.update_config(fields)  # type: ignore[no-any-return]


@router.post("/config/reset")
def reset_config(request: Request) -> dict[str, Any]:
    return request.app.state.session.reset_config()  # type: ignore[no-any-return]
