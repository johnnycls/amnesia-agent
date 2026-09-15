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

from home_config.store import (
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
            reloaded = store.load()
            self.assertEqual(reloaded.selected_character_id, "aurora")

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
                json.dumps({"selected_character_id": "kai", "extra": 1}),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                store.load()

    def test_non_string_selected_id_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AssistantConfigStore(directory)
            store.path.write_text(
                json.dumps({"selected_character_id": 42}),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                store.load()

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
