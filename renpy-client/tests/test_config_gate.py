"""Provider config gate and boot readiness tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from state.config_gate import (
    format_config_required_status,
    is_boot_ready,
    is_character_selected,
    is_provider_configured,
    next_setup_page,
    provider_config_gaps,
)


class ConfigGateTests(unittest.TestCase):
    def test_requires_model_and_api_key(self) -> None:
        self.assertEqual(
            provider_config_gaps({"model": "", "api_key_set": False}),
            ["model", "api_key"],
        )
        self.assertEqual(
            provider_config_gaps({"model": "  ", "api_key_set": True}),
            ["model"],
        )
        self.assertEqual(
            provider_config_gaps({"model": "openai/gpt-4o", "api_key_set": False}),
            ["api_key"],
        )
        self.assertTrue(
            is_provider_configured({"model": "openai/gpt-4o", "api_key_set": True})
        )

    def test_status_message(self) -> None:
        self.assertIn(
            "model",
            format_config_required_status(["model", "api_key"]).lower(),
        )
        self.assertIn(
            "api key",
            format_config_required_status(["model", "api_key"]).lower(),
        )


class ReadinessTests(unittest.TestCase):
    def test_character_selected_requires_matching_pack(self) -> None:
        self.assertFalse(is_character_selected("", {"aurora", "kai"}))
        self.assertFalse(is_character_selected("  ", {"aurora", "kai"}))
        self.assertFalse(is_character_selected("missing", {"aurora", "kai"}))
        self.assertTrue(is_character_selected("aurora", {"aurora", "kai"}))

    def test_next_setup_page_prefers_config(self) -> None:
        self.assertIsNone(next_setup_page(provider_ok=True, character_ok=True))
        self.assertEqual(
            next_setup_page(provider_ok=False, character_ok=False), "config"
        )
        self.assertEqual(
            next_setup_page(provider_ok=False, character_ok=True), "config"
        )
        self.assertEqual(
            next_setup_page(provider_ok=True, character_ok=False),
            "character_select",
        )

    def test_boot_ready(self) -> None:
        self.assertTrue(is_boot_ready(provider_ok=True, character_ok=True))
        self.assertFalse(is_boot_ready(provider_ok=True, character_ok=False))
        self.assertFalse(is_boot_ready(provider_ok=False, character_ok=True))


if __name__ == "__main__":
    unittest.main()
