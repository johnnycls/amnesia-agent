"""Health probe."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

# Empty path "" (not "/") so mount is /v1/health without a trailing slash.
router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(request: Request) -> dict[str, Any]:
    return request.app.state.session.health()  # type: ignore[no-any-return]
