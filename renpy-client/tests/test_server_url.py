"""Server URL parsing and persistence-facing client behavior."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import (  # noqa: E402
    DEFAULT_SERVER_URL,
    ServerUrlError,
    normalize_server_url,
)


class ServerUrlTests(unittest.TestCase):
    def test_normalizes_origins(self) -> None:
        self.assertEqual(normalize_server_url(DEFAULT_SERVER_URL), DEFAULT_SERVER_URL)
        self.assertEqual(
            normalize_server_url(" HTTPS://Agent.Example:9443/ "),
            "https://agent.example:9443",
        )
        self.assertEqual(
            normalize_server_url("http://[::1]:8765"),
            "http://[::1]:8765",
        )
        self.assertEqual(
            normalize_server_url("https://agent.example"),
            "https://agent.example",
        )

    def test_rejects_ambiguous_or_insecure_shapes(self) -> None:
        for value in (
            "",
            "ftp://agent.example:21",
            "http://agent.example:",
            "http://agent.example:8765/v1",
            "http://agent.example:8765?x=1",
            "http://user:pass@agent.example:8765",
            "http://agent.example:not-a-port",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ServerUrlError):
                    normalize_server_url(value)


if __name__ == "__main__":
    unittest.main()
