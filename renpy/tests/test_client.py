import sys
import tempfile
import types
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.client import ApiError  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
