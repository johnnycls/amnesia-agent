"""Assistant turn lifecycle tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, call

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import TurnTimeoutError  # noqa: E402
from audio.player import MusicPlayer  # noqa: E402
from characters.loader import MediaAsset  # noqa: E402
from state.app import AppState  # noqa: E402


class FakeTurnHandle:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def stream_turn(
        self,
        text: str,
        on_event: Any,
        on_error: Any,
        on_complete: Any,
        **kwargs: Any,
    ) -> FakeTurnHandle:
        handle = FakeTurnHandle()
        self.calls.append(
            {
                "text": text,
                "on_event": on_event,
                "on_error": on_error,
                "on_complete": on_complete,
                "handle": handle,
                **kwargs,
            }
        )
        return handle


class TurnLifecycleTests(unittest.TestCase):
    def _app(self) -> tuple[AppState, FakeClient]:
        app = AppState()
        client = FakeClient()
        app.client = client
        app.ready = True
        app.provider_configured = True
        app.character = SimpleNamespace(
            id="aurora",
            prompt="frontend character prompt",
            backgrounds={"room": MediaAsset("room.jpg", "image")},
            expressions={
                "neutral": MediaAsset("neutral.jpg", "image"),
                "busy": MediaAsset("busy.jpg", "image"),
            },
        )
        app.current_bg = "room"
        app.current_expression = "neutral"
        return app, client

    def test_stage_bgm_changes_once_and_same_track_does_not_restart(self) -> None:
        app, _ = self._app()
        app.character.bgms = {
            "default": "/packs/aurora/default.ogg",
            "tense": "/packs/aurora/tense.ogg",
        }
        app.current_bgm = "default"
        backend = Mock()
        app.music = MusicPlayer(backend)

        app._sync_stage_paths()
        app._apply_assistant_stage(
            {
                "message": "first",
                "choices": [],
                "bg": "room",
                "expression": "neutral",
                "bgm": "default",
            }
        )
        app._apply_assistant_stage(
            {
                "message": "second",
                "choices": [],
                "bg": "room",
                "expression": "neutral",
                "bgm": "tense",
            }
        )

        self.assertEqual(app.current_bgm, "tense")
        self.assertEqual(backend.play.call_args_list, [
            call("/packs/aurora/default.ogg", channel="music", loop=True),
            call("/packs/aurora/tense.ogg", channel="music", loop=True),
        ])

    def test_old_turn_completion_cannot_clear_new_turn(self) -> None:
        app, client = self._app()
        app.last_assistant_text = "partial response"

        app.send("first")
        first = client.calls[0]
        first["on_event"](
            {
                "type": "error",
                "data": {"message": "provider failed", "request_id": "abc123"},
            }
        )

        self.assertFalse(app.busy)
        self.assertEqual(app.last_assistant_text, "partial response")
        self.assertIn("abc123", app.status)

        app.send("second")
        second = client.calls[1]
        self.assertTrue(app.busy)
        self.assertNotEqual(app.active_turn_id, None)

        first["on_complete"]()

        self.assertTrue(app.busy)
        self.assertIs(app.turn_handle, second["handle"])
        self.assertEqual(app.active_turn_id, app.turn_id)

    def test_timeout_has_specific_retryable_status(self) -> None:
        app, client = self._app()
        app.send("slow request")
        client.calls[0]["on_error"](TurnTimeoutError("timed out"))

        self.assertFalse(app.busy)
        self.assertIn("Connection timed out", app.status)
        self.assertIn("may still be working", app.status)

    def test_old_transport_error_is_ignored_after_new_turn(self) -> None:
        app, client = self._app()
        app.send("first")
        first = client.calls[0]
        first["on_event"]({"type": "error", "data": {"message": "failed"}})
        app.send("second")
        second = client.calls[1]

        first["on_error"](RuntimeError("late failure"))

        self.assertTrue(app.busy)
        self.assertIs(app.turn_handle, second["handle"])


if __name__ == "__main__":
    unittest.main()
