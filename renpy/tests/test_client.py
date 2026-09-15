import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import ApiError, Client  # noqa: E402
from api.schema import ANSWER_WITH_CHOICES  # noqa: E402
from api.sse import SseError, parse_sse  # noqa: E402
import process.lifecycle as lifecycle  # noqa: E402


class ClientTests(unittest.TestCase):
    def test_parse_sse_decodes_data_lines(self) -> None:
        events = list(
            parse_sse(
                [
                    b": keepalive\n",
                    b'data: {"type":"delta","data":{"text":"hi"}}\n',
                    b"\n",
                    b'data: {"type":"done","data":{}}\n',
                ]
            )
        )
        self.assertEqual(events[0]["type"], "delta")
        self.assertEqual(events[1]["type"], "done")

    def test_parse_sse_rejects_malformed_json(self) -> None:
        with self.assertRaises(SseError):
            list(parse_sse([b"data: not-json\n"]))

    def test_answer_with_choices_schema_shape(self) -> None:
        self.assertEqual(ANSWER_WITH_CHOICES["type"], "json_schema")
        schema = ANSWER_WITH_CHOICES["json_schema"]
        self.assertEqual(schema["name"], "answer_with_choices")
        self.assertEqual(schema["schema"]["required"], ["answer", "choices"])

    def test_bundled_server_path_uses_game_directory(self) -> None:
        original_renpy = lifecycle.renpy
        try:
            with tempfile.TemporaryDirectory() as directory:
                server_directory = Path(directory) / "server"
                server_directory.mkdir()
                server_path = server_directory / lifecycle.BUNDLED_SERVER_NAME
                server_path.touch()
                lifecycle.renpy = types.SimpleNamespace(
                    config=types.SimpleNamespace(gamedir=directory)
                )
                self.assertEqual(lifecycle.bundled_server_path(), str(server_path))
        finally:
            lifecycle.renpy = original_renpy

    def test_api_error_is_runtime_error(self) -> None:
        self.assertTrue(issubclass(ApiError, RuntimeError))

    def test_stream_turn_cancel_still_invokes_on_complete(self) -> None:
        """Cancel must not leave the UI stuck busy: thread always signals complete."""
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        errors: list[Exception] = []

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def close(self) -> None:
                release.set()

            def __iter__(self):
                started.set()
                # Block until cancel closes us (or test times out).
                release.wait(timeout=2.0)
                # After cancel, raising simulates socket close mid-stream.
                raise OSError("response closed")

        client = Client(host="127.0.0.1", port=9)

        def on_event(event: dict) -> None:
            pass

        def on_error(error: Exception) -> None:
            errors.append(error)

        def on_complete() -> None:
            completed.set()

        # Patch invoke: under unittest the local renpy/ package shadows real Ren'Py.
        with (
            patch("api.client.urlopen", return_value=FakeResponse()),
            patch("api.client.invoke", side_effect=lambda cb, *a: cb(*a)),
        ):
            handle = client.stream_turn(
                "hi",
                "/tmp/ws",
                on_event,
                on_error,
                on_complete,
            )
            self.assertTrue(started.wait(timeout=2.0))
            handle.cancel()
            self.assertTrue(completed.wait(timeout=2.0))

        self.assertEqual(errors, [])
        self.assertTrue(handle.cancelled)


if __name__ == "__main__":
    unittest.main()
