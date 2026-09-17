"""Custom-scheme pairing link validation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.pairing import PairingLinkError, parse_pairing_link  # noqa: E402


class PairingLinkTests(unittest.TestCase):
    def test_parses_https_pairing_link(self) -> None:
        payload = parse_pairing_link(
            "amnesia://pair?v=1&server=https%3A%2F%2Fagent.example.com&code=abc"
        )
        self.assertEqual(payload.server_url, "https://agent.example.com")
        self.assertEqual(payload.code, "abc")

    def test_rejects_remote_http(self) -> None:
        with self.assertRaises(PairingLinkError):
            parse_pairing_link(
                "amnesia://pair?v=1&server=http%3A%2F%2Fagent.example.com&code=abc"
            )

    def test_rejects_wrong_scheme_and_version(self) -> None:
        for value in (
            "https://pair?v=1&server=https%3A%2F%2Fagent.example.com&code=abc",
            "amnesia://pair?v=2&server=https%3A%2F%2Fagent.example.com&code=abc",
        ):
            with self.subTest(value=value):
                with self.assertRaises(PairingLinkError):
                    parse_pairing_link(value)


if __name__ == "__main__":
    unittest.main()
