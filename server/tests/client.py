from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient as FastAPITestClient


class LocalTestClient(FastAPITestClient):
    """Test client representing a non-browser local API client."""

    def request(self, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-Amnesia-Client", "local")
        kwargs["headers"] = headers
        return super().request(method, url, *args, **kwargs)
