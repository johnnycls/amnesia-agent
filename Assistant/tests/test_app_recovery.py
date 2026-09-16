"""Startup configuration recovery tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import ApiError  # noqa: E402
from home_config.store import AssistantConfigStore  # noqa: E402
from state.app import AppState  # noqa: E402


class ImmediateThread:
    """Run a background target synchronously so tests stay deterministic."""

    def __init__(self, *, target: object, **_kwargs: object) -> None:
        self.target = target

    def start(self) -> None:
        self.target()  # type: ignore[operator]


class StartupRecoveryTests(unittest.TestCase):
    def _app(self, store: AssistantConfigStore) -> AppState:
        app = AppState()
        app.config_store = store
        app.server = SimpleNamespace(start=Mock())
        return app

    def test_corrupt_assistant_config_selects_assistant_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text("{bad", encoding="utf-8")
            app = self._app(store)
            app.client = SimpleNamespace(health=lambda timeout: {"status": "ok"})

            with (
                patch("state.app.load_all_characters", return_value=[object(), object()]),
                patch("state.app.threading.Thread", ImmediateThread),
            ):
                app.start_loading()

            self.assertEqual(app.loading_recovery, "assistant_config")
            self.assertFalse(app.recovery_busy)
            self.assertFalse(app.ready)

    def test_corrupt_server_config_selects_server_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.write_defaults()
            app = self._app(store)

            def request_json(method: str, path: str, **_kwargs: object) -> object:
                if method == "GET" and path == "/v1/config":
                    raise ApiError("Malformed server configuration")
                raise AssertionError((method, path))

            app.client = SimpleNamespace(
                health=lambda timeout: {"status": "ok"},
                request_json=request_json,
            )

            with (
                patch("state.app.load_all_characters", return_value=[object(), object()]),
                patch("state.app.threading.Thread", ImmediateThread),
            ):
                app.start_loading()

            self.assertEqual(app.loading_recovery, "server_config")
            self.assertFalse(app.recovery_busy)
            self.assertFalse(app.ready)

    def test_server_config_reset_reloads_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            app = self._app(store)
            app.loading_recovery = "server_config"
            app.start_loading = Mock()  # type: ignore[method-assign]
            requests: list[tuple[str, str]] = []

            def request_json(method: str, path: str, **_kwargs: object) -> dict[str, object]:
                requests.append((method, path))
                return {}

            app.client = SimpleNamespace(request_json=request_json)

            with patch("state.app.threading.Thread", ImmediateThread):
                app.reset_server_config()

            self.assertEqual(requests, [("POST", "/v1/config/reset")])
            self.assertFalse(app.recovery_busy)
            app.start_loading.assert_called_once_with()  # type: ignore[attr-defined]

    def test_assistant_config_reset_reloads_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.set_selected_character("aurora")
            app = self._app(store)
            app.loading_recovery = "assistant_config"
            app.start_loading = Mock()  # type: ignore[method-assign]

            with patch("state.app.threading.Thread", ImmediateThread):
                app.reset_assistant_config()

            self.assertFalse(app.recovery_busy)
            self.assertEqual(store.load().selected_character_id, "")
            self.assertEqual(store.load().language, "english")
            app.start_loading.assert_called_once_with()  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
