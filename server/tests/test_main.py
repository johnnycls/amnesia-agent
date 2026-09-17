"""CLI / bind-host helpers (no live server)."""

from __future__ import annotations

import unittest

from amnesia_agent_server.__main__ import is_loopback_host, main


class IsLoopbackHostTests(unittest.TestCase):
    def test_loopback_literals(self) -> None:
        for host in (
            "127.0.0.1",
            "localhost",
            "LOCALHOST",
            "::1",
            "[::1]",
            "127.0.0.2",
            " 127.0.0.1 ",
        ):
            with self.subTest(host=host):
                self.assertTrue(is_loopback_host(host))

    def test_non_loopback(self) -> None:
        for host in (
            "0.0.0.0",
            "::",
            "[::]",
            "192.168.1.1",
            "10.0.0.1",
            "example.com",
            "",
        ):
            with self.subTest(host=host):
                self.assertFalse(is_loopback_host(host))


class MainBindGuardTests(unittest.TestCase):
    def test_refuses_non_loopback_hosts(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--host", "0.0.0.0", "--port", "8765"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_allow_remote_option_is_removed(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--host", "0.0.0.0", "--allow-remote", "--port", "8765"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
