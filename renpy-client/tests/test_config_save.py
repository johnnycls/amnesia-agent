"""Config save payload tests (api_key omit-when-blank)."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from home_config.store import AssistantConfig  # noqa: E402
from state.app import AppState  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if method == "PUT" and path == "/v1/config":
            assert payload is not None
            self.puts.append(dict(payload))
            return {
                "model": payload["model"],
                "api_key_set": True,
                "base_url": payload.get("base_url") or None,
                "provider_params": payload.get("provider_params") or {},
            }
        raise AssertionError(f"unexpected {method} {path}")


class ConfigSavePayloadTests(unittest.TestCase):
    def _prepare(self, *, api_key_set: bool) -> tuple[AppState, FakeClient, threading.Event]:
        app = AppState()
        client = FakeClient()
        app.client = client
        app.config_store = Mock()
        app.config_store.set_language.return_value = AssistantConfig(
            selected_character_id="aurora",
            language="english",
        )
        app.settings_api_key_set = api_key_set
        app.provider_configured = api_key_set
        app.ready = True
        done = threading.Event()
        original = app._config_saved

        def _saved(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            done.set()

        app._config_saved = _saved  # type: ignore[method-assign]
        return app, client, done

    def test_blank_api_key_is_omitted_when_key_already_set(self) -> None:
        app, client, done = self._prepare(api_key_set=True)
        app.save_config_form(
            language="english",
            model="openai/gpt-4o",
            api_key="",
            base_url="",
            provider_params_text="{}",
        )
        self.assertTrue(done.wait(2.0), "save callback did not finish")
        self.assertEqual(len(client.puts), 1)
        self.assertNotIn("api_key", client.puts[0])
        self.assertEqual(client.puts[0]["model"], "openai/gpt-4o")

    def test_non_empty_api_key_is_included(self) -> None:
        app, client, done = self._prepare(api_key_set=False)
        app.save_config_form(
            language="english",
            model="openai/gpt-4o",
            api_key=" sk-test ",
            base_url="",
            provider_params_text="{}",
        )
        self.assertTrue(done.wait(2.0), "save callback did not finish")
        self.assertEqual(client.puts[0]["api_key"], "sk-test")


if __name__ == "__main__":
    unittest.main()
