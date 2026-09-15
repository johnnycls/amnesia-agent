"""Provider config gate tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from state.config_gate import (
    format_config_required_status,
    is_provider_configured,
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


if __name__ == "__main__":
    unittest.main()
