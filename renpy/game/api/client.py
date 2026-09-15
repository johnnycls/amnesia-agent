"""Standard-library HTTP + SSE client (no FastAPI / LiteLLM / kernel imports)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from api.schema import ANSWER_WITH_CHOICES
from api.sse import SseError, parse_sse

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class ApiError(RuntimeError):
    """Raised when the local server cannot be reached or returns an error."""


class TurnHandle:
    """Cancellable SSE turn: cancel closes the HTTP response (server disconnect)."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._response: Any = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def attach(self, response: Any) -> None:
        with self._lock:
            self._response = response
            if self.cancelled:
                response.close()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            response = self._response
        if response is not None:
            response.close()


def invoke(callback: Callable[..., None], *args: Any) -> None:
    """Dispatch to Ren'Py's main thread when running inside the game."""
    if renpy is not None:
        renpy.invoke_in_main_thread(callback, *args)
    else:
        callback(*args)


class Client:
    """Synchronous JSON requests and background SSE turns against /v1."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            detail = _http_error_detail(error)
            raise ApiError(detail) from error
        except (URLError, OSError) as error:
            raise ApiError(f"Local server request failed: {error}") from error
        if not raw.strip():
            return {}
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ApiError("Local server returned invalid JSON") from error
        if not isinstance(value, dict):
            raise ApiError("Local server returned a non-object response")
        if "detail" in value and len(value) == 1:
            raise ApiError(str(value["detail"]))
        return value

    def health(self, timeout: float = 0.5) -> dict[str, Any]:
        return self.request_json("GET", "/v1/health", timeout=timeout)

    def stream_turn(
        self,
        text: str,
        workspace_path: str,
        on_event: Callable[[dict[str, Any]], None],
        on_error: Callable[[Exception], None],
        on_complete: Callable[[], None],
        response_format: dict[str, Any] | None = None,
    ) -> TurnHandle:
        """POST /v1/turn with answer_with_choices by default; cancel = disconnect."""
        handle = TurnHandle()
        payload: dict[str, Any] = {
            "text": text,
            "workspace_path": workspace_path,
            "response_format": (
                ANSWER_WITH_CHOICES if response_format is None else response_format
            ),
        }

        def run() -> None:
            request = Request(
                self.base_url + "/v1/turn",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=None) as response:
                    handle.attach(response)
                    for event in parse_sse(response):
                        if handle.cancelled:
                            return
                        invoke(on_event, event)
                        if event.get("type") == "done":
                            invoke(on_complete)
                            return
                        if event.get("type") == "error":
                            # Stream already delivered the error envelope.
                            invoke(on_complete)
                            return
            except (HTTPError, URLError, OSError, SseError) as error:
                if not handle.cancelled:
                    if isinstance(error, HTTPError):
                        invoke(on_error, ApiError(_http_error_detail(error)))
                    elif isinstance(error, SseError):
                        invoke(on_error, ApiError(str(error)))
                    else:
                        invoke(on_error, ApiError(f"Turn request failed: {error}"))
            except Exception as error:  # noqa: BLE001 — surface to UI
                if not handle.cancelled:
                    invoke(on_error, error)

        threading.Thread(target=run, name="amnesia-agent-turn", daemon=True).start()
        return handle


def _http_error_detail(error: HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8")
        value = json.loads(raw)
        if isinstance(value, dict) and "detail" in value:
            return str(value["detail"])
    except Exception:  # noqa: BLE001
        pass
    return f"Local server HTTP {error.code}: {error.reason}"
