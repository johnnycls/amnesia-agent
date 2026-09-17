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
                "bgm": "tense",
            },
            background_ids={"room", "outdoor"},
            expression_ids={"neutral", "smile"},
            bgm_ids={"default", "tense"},
            previous_bg="room",
            previous_expression="neutral",
            previous_bgm="default",
        )
        self.assertEqual(result.message, "Hello")
        self.assertEqual(result.choices, ["A", "B"])
        self.assertEqual(result.bg, "outdoor")
        self.assertEqual(result.expression, "smile")
        self.assertEqual(result.bgm, "tense")
        self.assertEqual(result.warnings, [])

    def test_invalid_ids_keep_previous_and_warn(self) -> None:
        result = apply_stage(
            {
                "message": "Hmm",
                "choices": ["ok"],
                "bg": "spaceship",
                "expression": "angry",
                "bgm": "missing",
            },
            background_ids={"room", "outdoor"},
            expression_ids={"neutral", "smile"},
            bgm_ids={"default", "tense"},
            previous_bg="room",
            previous_expression="neutral",
            previous_bgm="default",
        )
        self.assertEqual(result.bg, "room")
        self.assertEqual(result.expression, "neutral")
        self.assertEqual(result.bgm, "default")
        self.assertEqual(len(result.warnings), 3)

    def test_missing_bgm_keeps_previous_and_warns(self) -> None:
        result = apply_stage(
            {
                "message": "x",
                "choices": [],
                "bg": "room",
                "expression": "neutral",
            },
            background_ids={"room"},
            expression_ids={"neutral"},
            bgm_ids={"default"},
            previous_bg="room",
            previous_expression="neutral",
            previous_bgm="default",
        )
        self.assertEqual(result.bgm, "default")
        self.assertEqual(result.warnings, ["Missing bgm; kept 'default'"])

    def test_non_string_choices_filtered(self) -> None:
        result = apply_stage(
            {
                "message": "x",
                "choices": ["ok", 1, None],
                "bg": "room",
                "expression": "neutral",
                "bgm": "default",
            },
            background_ids={"room"},
            expression_ids={"neutral"},
            bgm_ids={"default"},
            previous_bg="room",
            previous_expression="neutral",
            previous_bgm="default",
        )
        self.assertEqual(result.choices, ["ok"])
        self.assertEqual(result.bgm, "default")


if __name__ == "__main__":
    unittest.main()
