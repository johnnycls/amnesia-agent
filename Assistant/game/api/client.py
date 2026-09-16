"""Standard-library HTTP + SSE client (no FastAPI / LiteLLM / kernel imports)."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from api.schema import ASSISTANT_STAGE
from api.sse import SseError, parse_sse

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TURN_CONNECT_TIMEOUT_SECONDS = 10.0
TURN_IDLE_TIMEOUT_SECONDS = 120.0
_TURN_EVENT_TYPES = frozenset({"delta", "assistant", "tool_result", "error", "done"})
_LOCAL_CLIENT_HEADER = "X-Amnesia-Client"
_LOCAL_CLIENT_MARKER = "local"


class ApiError(RuntimeError):
    """Raised when the local server cannot be reached or returns an error."""


class TurnTimeoutError(ApiError):
    """Raised when a turn cannot connect or produces no data for too long."""


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
        headers = {_LOCAL_CLIENT_HEADER: _LOCAL_CLIENT_MARKER}
        if body is not None:
            headers["Content-Type"] = "application/json"
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
        on_event: Callable[[dict[str, Any]], None],
        on_error: Callable[[Exception], None],
        on_complete: Callable[[], None],
        response_format: dict[str, Any] | None = None,
        system_prompt_prefix: str = "",
    ) -> TurnHandle:
        """POST /v1/turn omitting workspace_path (server default ~/.amnesia-agent)."""
        handle = TurnHandle()
        payload: dict[str, Any] = {
            "text": text,
            "response_format": (
                ASSISTANT_STAGE if response_format is None else response_format
            ),
        }
        payload["system_prompt_prefix"] = system_prompt_prefix

        def run() -> None:
            # Always invoke on_complete unless on_error already handled the turn
            # (including cancel: early return or socket close after handle.cancel).
            need_complete = True
            request = Request(
                self.base_url + "/v1/turn",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    _LOCAL_CLIENT_HEADER: _LOCAL_CLIENT_MARKER,
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=TURN_CONNECT_TIMEOUT_SECONDS) as response:
                    _set_response_timeout(response, TURN_IDLE_TIMEOUT_SECONDS)
                    handle.attach(response)
                    terminal = False
                    for raw_event in parse_sse(response):
                        if handle.cancelled:
                            return
                        event = validate_turn_event(raw_event)
                        invoke(on_event, event)
                        if event.get("type") in ("done", "error"):
                            terminal = True
                            if event.get("type") == "error":
                                need_complete = False
                            return
                    if not handle.cancelled and not terminal:
                        raise SseError("Turn stream ended without a terminal event")
            except (HTTPError, URLError, OSError, SseError) as error:
                if not handle.cancelled:
                    need_complete = False
                    if isinstance(error, HTTPError):
                        invoke(on_error, ApiError(_http_error_detail(error)))
                    elif isinstance(error, SseError):
                        invoke(on_error, ApiError(str(error)))
                    elif _is_timeout_error(error):
                        invoke(
                            on_error,
                            TurnTimeoutError(
                                "Connection timed out while waiting for the provider."
                            ),
                        )
                    else:
                        invoke(on_error, ApiError(f"Turn request failed: {error}"))
            except Exception as error:  # noqa: BLE001 — surface to UI
                if not handle.cancelled:
                    need_complete = False
                    invoke(on_error, error)
            finally:
                if need_complete:
                    invoke(on_complete)

        threading.Thread(target=run, name="assistant-turn", daemon=True).start()
        return handle


def _set_response_timeout(response: Any, timeout: float) -> None:
    """Switch the connected urllib socket from connect to idle timeout."""
    try:
        socket_object = response.fp.raw._sock
        socket_object.settimeout(timeout)
    except (AttributeError, OSError):
        # Test doubles and alternate urllib handlers may not expose the socket.
        pass


def _is_timeout_error(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return isinstance(error, URLError) and isinstance(error.reason, (TimeoutError, socket.timeout))


def validate_turn_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate the small event contract consumed by the Assistant UI."""
    event_type = event.get("type")
    data = event.get("data")
    if event_type not in _TURN_EVENT_TYPES:
        raise SseError(f"Local server returned unknown turn event: {event_type!r}")
    if not isinstance(data, dict):
        raise SseError(f"Turn event {event_type!r} data must be an object")
    if event_type == "delta" and not isinstance(data.get("text"), str):
        raise SseError("Turn delta event text must be a string")
    if event_type == "assistant":
        content = data.get("content")
        if content is not None and not isinstance(content, str):
            raise SseError("Assistant event content must be a string or null")
        tool_calls = data.get("tool_calls")
        if tool_calls is not None and not isinstance(tool_calls, list):
            raise SseError("Assistant event tool_calls must be an array")
    elif event_type == "tool_result" and not isinstance(data.get("content"), str):
        raise SseError("Tool result event content must be a string")
    elif event_type == "error" and not isinstance(data.get("message"), str):
        raise SseError("Turn error event message must be a string")
    return event


def _http_error_detail(error: HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8")
        value = json.loads(raw)
        if isinstance(value, dict) and "detail" in value:
            return str(value["detail"])
    except Exception:  # noqa: BLE001
        pass
    return f"Local server HTTP {error.code}: {error.reason}"
