"""SSE parser smoke tests (copied behaviour, independent module)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.sse import SseError, parse_sse  # noqa: E402


class SseTests(unittest.TestCase):
    def test_parse_sse_decodes_data_lines(self) -> None:
        events = list(
            parse_sse(
                [
                    b": keepalive\n",
                    b'data: {"type":"assistant","data":{"message":"hi"}}\n',
                    b'data: {"type":"done","data":{}}\n',
                ]
            )
        )
        self.assertEqual(events[0]["type"], "assistant")
        self.assertEqual(events[1]["type"], "done")

    def test_parse_sse_rejects_malformed_json(self) -> None:
        with self.assertRaises(SseError):
            list(parse_sse([b"data: not-json\n"]))


if __name__ == "__main__":
    unittest.main()
