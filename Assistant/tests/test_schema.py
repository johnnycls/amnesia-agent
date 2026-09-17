"""assistant_stage schema constant tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from api.schema import ASSISTANT_STAGE  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_assistant_stage_shape(self) -> None:
        self.assertEqual(ASSISTANT_STAGE["type"], "json_schema")
        schema = ASSISTANT_STAGE["json_schema"]
        self.assertEqual(schema["name"], "assistant_stage")
        self.assertTrue(schema["strict"])
        required = schema["schema"]["required"]
        self.assertEqual(required, ["message", "choices", "bg", "expression", "bgm"])
        props = schema["schema"]["properties"]
        self.assertEqual(props["message"]["type"], "string")
        self.assertEqual(props["choices"]["type"], "array")
        self.assertEqual(props["bg"]["type"], "string")
        self.assertEqual(props["expression"]["type"], "string")
        self.assertEqual(props["bgm"]["type"], "string")
        self.assertFalse(schema["schema"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
