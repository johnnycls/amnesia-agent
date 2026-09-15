import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from state.app import format_history_messages  # noqa: E402


class HistoryFormatTests(unittest.TestCase):
    def test_formats_role_msg_time_and_collapses_whitespace(self) -> None:
        text = format_history_messages(
            [
                {
                    "role": "user",
                    "content": "hello\nworld",
                    "timestamp": "2026-09-15T08:55:01+00:00",
                },
                {"role": "assistant", "content": None},
                {"role": "tool", "content": 42},
            ]
        )
        self.assertEqual(
            text,
            "user: hello world 2026-09-15T08:55:01+00:00\n"
            "assistant:  —\n"
            "tool: 42 —",
        )

    def test_missing_timestamp_uses_em_dash(self) -> None:
        self.assertEqual(
            format_history_messages([{"role": "user", "content": "hi"}]),
            "user: hi —",
        )

    def test_empty_or_invalid_input(self) -> None:
        self.assertEqual(format_history_messages([]), "")
        self.assertEqual(format_history_messages(None), "")
        self.assertEqual(format_history_messages("nope"), "")


if __name__ == "__main__":
    unittest.main()
