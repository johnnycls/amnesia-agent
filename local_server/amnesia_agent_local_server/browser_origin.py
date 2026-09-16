"""Browser-origin policy for the loopback HTTP API."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_CLIENT_HEADER = "x-amnesia-client"
LOCAL_CLIENT_MARKER = "local"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_allowed_browser_origin(origin: str | None) -> bool:
    """Return whether a browser origin is allowed to access the local API.

    Missing ``Origin`` is allowed for non-browser clients such as Ren'Py and
    command-line tools. Browser origins must use HTTP and resolve to localhost
    or a loopback IP address. ``null`` origins, including ``file://`` pages,
    are deliberately rejected.
    """
    if origin is None:
        return True
    if origin == "null":
        return False

    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False

    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (port is None and ":" in parsed.netloc and not parsed.netloc.startswith("["))
    ):
        return False

    host = parsed.hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class BrowserOriginMiddleware:
    """Reject explicit browser origins outside the trusted local origins."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_values: dict[str, list[str]] = {}
        for key, value in scope["headers"]:
            name = key.decode("latin-1")
            header_values.setdefault(name, []).append(value.decode("latin-1"))

        origins = header_values.get("origin", [])
        origin = origins[0] if len(origins) == 1 else None
        if len(origins) > 1 or not is_allowed_browser_origin(origin):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Browser origin is not allowed."},
            )
            await response(scope, receive, send)
            return

        if (
            scope["method"] not in _SAFE_METHODS
            and origin is None
            and header_values.get(LOCAL_CLIENT_HEADER) != [LOCAL_CLIENT_MARKER]
        ):
            response = JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Originless state-changing requests must include "
                        "X-Amnesia-Client: local."
                    )
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
