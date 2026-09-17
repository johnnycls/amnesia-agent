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

    def test_startup_never_owns_server_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(AssistantConfigStore(directory))
            app.client = SimpleNamespace(
                set_base_url=Mock(),
                health=lambda timeout: {"status": "ok"},
                request_json=lambda method, path, **kwargs: {},
            )
            app._loading_ok = Mock()  # type: ignore[method-assign]

            with (
                patch("state.app.load_all_characters", return_value=[object()]),
                patch("state.app.threading.Thread", ImmediateThread),
            ):
                app.start_loading()

            self.assertFalse(hasattr(app, "server"))
            app.client.set_base_url.assert_called_once()  # type: ignore[attr-defined]

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
                set_base_url=Mock(),
            )

            with (
                patch("state.app.load_all_characters", return_value=[object(), object()]),
                patch("state.app.threading.Thread", ImmediateThread),
            ):
                app.start_loading()

            self.assertEqual(app.loading_recovery, "server_config")
            self.assertFalse(app.recovery_busy)
            self.assertFalse(app.ready)

    def test_character_apply_does_not_write_kernel_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(AssistantConfigStore(directory))
            requests: list[tuple[str, str]] = []

            def request_json(method: str, path: str, **_kwargs: object) -> dict[str, object]:
                requests.append((method, path))
                return {}

            app.client = SimpleNamespace(request_json=request_json)
            app._character_ready = Mock()  # type: ignore[method-assign]
            pack = SimpleNamespace(prompt="frontend prompt")

            with patch("state.app.threading.Thread", ImmediateThread):
                app._begin_apply_character(pack, status_when_ready="Ready")

            self.assertEqual(requests, [("POST", "/v1/workspace/setup-or-repair")])

    def test_stale_loading_callback_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = self._app(AssistantConfigStore(directory))
            first = app._begin_operation("loading_config")
            app._end_operation(first)
            second = app._begin_operation("saving_config")
            app.status = "Saving settings..."

            app._loading_failed(RuntimeError("stale"), "", first)

            self.assertEqual(app.operation_id, second)
            self.assertEqual(app.operation, "saving_config")
            self.assertEqual(app.status, "Saving settings...")

    def test_custom_server_url_is_persisted_after_health(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            app = self._app(store)
            app.start_loading = Mock()  # type: ignore[method-assign]
            app.client = SimpleNamespace(
                set_base_url=Mock(),
                health=lambda timeout: {"status": "ok"},
            )

            with patch("state.app.threading.Thread", ImmediateThread):
                app.connect_server("https://agent.example:9443/")

            self.assertEqual(store.load().server_url, "https://agent.example:9443")
            app.start_loading.assert_called_once_with()  # type: ignore[attr-defined]

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
