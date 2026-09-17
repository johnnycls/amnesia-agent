"""Unauthenticated one-time remote pairing exchange."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/pair", tags=["pairing"])


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    device_name: str = Field(default="device", max_length=120)


@router.post("")
def pair(body: PairRequest, request: Request) -> dict[str, str]:
    manager = request.app.state.pairing_manager
    _payload, token = manager.consume(body.code, body.device_name)
    return {
        "server_url": manager.public_url,
        "device_token": token,
    }
