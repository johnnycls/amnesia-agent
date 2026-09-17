"""Bearer authentication middleware for remote deployments."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from amnesia_agent_server.pairing import DeviceTokenStore


class RemoteAuthMiddleware:
    """Require a device bearer token for every remote API route except pairing."""

    def __init__(self, app: ASGIApp, device_tokens: DeviceTokenStore) -> None:
        self.app = app
        self.device_tokens = device_tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path == "/v1/pair" or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        authorization = [
            value.decode("latin-1")
            for key, value in scope["headers"]
            if key.lower() == b"authorization"
        ]
        token = _bearer_token(authorization)
        if token is None or not self.device_tokens.authenticate(token):
            response = JSONResponse(
                status_code=401,
                content={"detail": "A valid bearer token is required."},
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _bearer_token(values: list[str]) -> str | None:
    if len(values) != 1:
        return None
    scheme, separator, token = values[0].partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token
