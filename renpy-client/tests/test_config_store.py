"""Assistant home config store tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import DEFAULT_SERVER_URL  # noqa: E402
from home_config.store import (  # noqa: E402
    DEFAULT_LANGUAGE,
    AssistantConfigStore,
    ConfigError,
    default_config_dict,
)


class AssistantConfigStoreTests(unittest.TestCase):
    def test_missing_file_lazy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            config = store.load()
            self.assertEqual(config.selected_character_id, "")
            self.assertEqual(config.language, DEFAULT_LANGUAGE)
            self.assertTrue(store.path.is_file())
            self.assertEqual(
                json.loads(store.path.read_text(encoding="utf-8")),
                default_config_dict(),
            )

    def test_set_selected_character_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.load()
            updated = store.set_selected_character("aurora")
            self.assertEqual(updated.selected_character_id, "aurora")
            self.assertEqual(updated.language, DEFAULT_LANGUAGE)
            reloaded = store.load()
            self.assertEqual(reloaded.selected_character_id, "aurora")
            self.assertEqual(reloaded.language, DEFAULT_LANGUAGE)

    def test_set_language_persists_and_preserves_character(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.set_selected_character("kai")
            updated = store.set_language("schinese")
            self.assertEqual(updated.language, "schinese")
            self.assertEqual(updated.selected_character_id, "kai")
            reloaded = store.load()
            self.assertEqual(reloaded.language, "schinese")
            self.assertEqual(reloaded.selected_character_id, "kai")

    def test_missing_language_defaults_english(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.write_text(
                json.dumps({"selected_character_id": "aurora"}),
                encoding="utf-8",
            )
            config = store.load()
            self.assertEqual(config.language, "english")
            self.assertEqual(config.selected_character_id, "aurora")

    def test_unsupported_language_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.write_text(
                json.dumps(
                    {"selected_character_id": "", "language": "klingon"}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                store.load()

    def test_corrupt_json_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                store.load()

    def test_unexpected_property_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.write_text(
                json.dumps(
                    {
                        "selected_character_id": "kai",
                        "language": "english",
                        "extra": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                store.load()

    def test_non_string_selected_id_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.write_text(
                json.dumps({"selected_character_id": 42, "language": "english"}),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                store.load()

    def test_default_keys_include_language(self) -> None:
        raw = default_config_dict()
        self.assertEqual(
            set(raw), {"selected_character_id", "language", "server_url", "server_token"}
        )
        self.assertEqual(raw["language"], "english")
        self.assertEqual(raw["server_url"], DEFAULT_SERVER_URL)

    @unittest.skipIf(
        os.name == "nt",
        "NTFS ignores POSIX 0o600; st_mode & 0o777 stays 0o666 on Windows",
    )
    def test_atomic_write_sets_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.write_defaults()
            mode = store.path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
