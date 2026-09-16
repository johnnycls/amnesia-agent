"""SSE parser smoke tests (copied behaviour, independent module)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import (  # noqa: E402
    ApiError,
    Client,
    TurnTimeoutError,
    validate_turn_event,
)
from api.sse import SseError, parse_sse  # noqa: E402


class FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)

    def close(self) -> None:
        return None


class SseTests(unittest.TestCase):
    def test_parse_sse_decodes_data_lines(self) -> None:
        events = list(
            parse_sse(
                [
                    b": keepalive\n",
                    b'data: {"type":"assistant","data":{"message":"hi"}}\n',
                    b'data: {"type":"done","data":{}}\n',
                ]
            )
        )
        self.assertEqual(events[0]["type"], "assistant")
        self.assertEqual(events[1]["type"], "done")

    def test_parse_sse_rejects_malformed_json(self) -> None:
        with self.assertRaises(SseError):
            list(parse_sse([b"data: not-json\n"]))

    def test_validate_turn_event_rejects_unknown_shape(self) -> None:
        with self.assertRaises(SseError):
            validate_turn_event({"type": "mystery", "data": {}})
        with self.assertRaises(SseError):
            validate_turn_event({"type": "delta", "data": {"text": 42}})

    def test_error_event_does_not_invoke_complete(self) -> None:
        import threading
        from unittest.mock import patch

        events: list[dict[str, object]] = []
        errors: list[Exception] = []
        completed = threading.Event()
        handle_done = threading.Event()

        def on_complete() -> None:
            completed.set()

        with patch(
            "api.client.urlopen",
            return_value=FakeResponse(
                [b'data: {"type":"error","data":{"message":"failed"}}\n']
            ),
        ):
            Client().stream_turn(
                "hello",
                events.append,
                errors.append,
                on_complete,
            )
            handle_done.set()
            self.assertTrue(handle_done.wait(timeout=1))

        # Give the daemon worker a deterministic chance to finish its callback.
        import time

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not events and not errors:
            time.sleep(0.01)
        self.assertEqual(len(events), 1)
        self.assertFalse(errors)
        self.assertFalse(completed.is_set())

    def test_connect_timeout_is_reported_as_turn_timeout(self) -> None:
        import time
        from unittest.mock import patch

        errors: list[Exception] = []
        with patch("api.client.urlopen", side_effect=TimeoutError()):
            Client().stream_turn("hello", lambda _event: None, errors.append, lambda: None)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not errors:
                time.sleep(0.01)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TurnTimeoutError)

    def test_incomplete_stream_is_client_error(self) -> None:
        import threading
        import time
        from unittest.mock import patch

        errors: list[Exception] = []
        completed = threading.Event()
        with patch("api.client.urlopen", return_value=FakeResponse([])):
            Client().stream_turn("hello", lambda _event: None, errors.append, completed.set)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not errors:
                time.sleep(0.01)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ApiError)
        self.assertFalse(completed.is_set())


if __name__ == "__main__":
    unittest.main()
