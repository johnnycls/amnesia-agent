"""CLI / bind-host helpers (no live server)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from amnesia_agent_local_server.__main__ import is_loopback_host, main


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
    def test_refuses_non_loopback_without_flag(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--host", "0.0.0.0", "--port", "8765"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_allow_remote_warns_and_would_start(self) -> None:
        warned: list[str] = []

        def fake_print(*args: object, **kwargs: object) -> None:
            warned.append(" ".join(str(a) for a in args))

        with (
            patch("amnesia_agent_local_server.__main__.print", side_effect=fake_print),
            patch("amnesia_agent_local_server.__main__.create_app") as create_app,
            patch("amnesia_agent_local_server.__main__.uvicorn.Config") as config_cls,
            patch("amnesia_agent_local_server.__main__.uvicorn.Server") as server_cls,
            patch("amnesia_agent_local_server.__main__.asyncio.run") as run,
        ):
            app = create_app.return_value
            app.state.uvicorn_server = None
            server_cls.return_value.serve = lambda: None
            main(["--host", "0.0.0.0", "--allow-remote", "--port", "8765"])

        self.assertTrue(any("WARNING" in line and "no auth" in line.lower() for line in warned))
        config_cls.assert_called_once()
        self.assertEqual(config_cls.call_args.kwargs["host"], "0.0.0.0")
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
