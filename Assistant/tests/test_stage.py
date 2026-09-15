"""Stage apply validation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from state.stage import apply_stage  # noqa: E402


class StageApplyTests(unittest.TestCase):
    def test_valid_ids_applied(self) -> None:
        result = apply_stage(
            {
                "message": "Hello",
                "choices": ["A", "B"],
                "bg": "outdoor",
                "expression": "smile",
            },
            background_ids={"room", "outdoor"},
            expression_ids={"neutral", "smile"},
            previous_bg="room",
            previous_expression="neutral",
        )
        self.assertEqual(result.message, "Hello")
        self.assertEqual(result.choices, ["A", "B"])
        self.assertEqual(result.bg, "outdoor")
        self.assertEqual(result.expression, "smile")
        self.assertEqual(result.warnings, [])

    def test_invalid_ids_keep_previous_and_warn(self) -> None:
        result = apply_stage(
            {
                "message": "Hmm",
                "choices": ["ok"],
                "bg": "spaceship",
                "expression": "angry",
            },
            background_ids={"room", "outdoor"},
            expression_ids={"neutral", "smile"},
            previous_bg="room",
            previous_expression="neutral",
        )
        self.assertEqual(result.bg, "room")
        self.assertEqual(result.expression, "neutral")
        self.assertEqual(len(result.warnings), 2)

    def test_non_string_choices_filtered(self) -> None:
        result = apply_stage(
            {"message": "x", "choices": ["ok", 1, None], "bg": "room", "expression": "neutral"},
            background_ids={"room"},
            expression_ids={"neutral"},
            previous_bg="room",
            previous_expression="neutral",
        )
        self.assertEqual(result.choices, ["ok"])


if __name__ == "__main__":
    unittest.main()
