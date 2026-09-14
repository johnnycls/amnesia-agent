"""Health probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return request.app.state.session.health()  # type: ignore[no-any-return]
