"""Ren'Py persistent preference adapter tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

import home_config.store as store  # noqa: E402
from home_config.store import (  # noqa: E402
    AssistantConfig,
    PersistentAssistantConfigStore,
)


class PersistentStoreTests(unittest.TestCase):
    def test_round_trip_uses_persistent_fields(self) -> None:
        persistent = SimpleNamespace()
        fake_renpy = SimpleNamespace(
            store=SimpleNamespace(persistent=persistent),
            save_persistent=Mock(),
        )
        with patch.object(store, "renpy", fake_renpy):
            preferences = PersistentAssistantConfigStore()
            preferences.save(AssistantConfig("creator.character", "japanese"))
            self.assertEqual(preferences.load().selected_character_id, "creator.character")
            self.assertEqual(preferences.load().language, "japanese")
            fake_renpy.save_persistent.assert_called_once_with()

    def test_reset_only_clears_assistant_fields(self) -> None:
        persistent = SimpleNamespace(
            selected_character_id="creator.character",
            assistant_language="japanese",
            unrelated_preference=True,
        )
        fake_renpy = SimpleNamespace(
            store=SimpleNamespace(persistent=persistent),
            save_persistent=Mock(),
        )
        with patch.object(store, "renpy", fake_renpy):
            PersistentAssistantConfigStore().reset()
            self.assertEqual(persistent.selected_character_id, "")
            self.assertEqual(persistent.assistant_language, "english")
            self.assertTrue(persistent.unrelated_preference)


if __name__ == "__main__":
    unittest.main()
