"""Character pack loader tests (no Ren'Py)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from characters.loader import (  # noqa: E402
    CharacterError,
    list_character_ids,
    load_all_characters,
    load_character,
)


class CharacterPackTests(unittest.TestCase):
    def test_bundled_packs_load(self) -> None:
        packs = load_all_characters()
        ids = {p.id for p in packs}
        self.assertEqual(ids, {"aurora", "kai"})
        for pack in packs:
            self.assertTrue(pack.display_name)
            self.assertTrue(pack.prompt.strip())
            self.assertIn(pack.default_bg, pack.backgrounds)
            self.assertIn(pack.default_expression, pack.expressions)
            self.assertIn("busy", pack.expressions)
            for name in ("neutral", "smile", "think", "busy", "surprised", "sad", "shy"):
                self.assertIn(name, pack.expressions)
            for path in pack.backgrounds.values():
                self.assertTrue(Path(path).is_file(), path)
            for path in pack.expressions.values():
                self.assertTrue(Path(path).is_file(), path)
            self.assertIsNotNone(pack.portrait_path())

    def test_list_character_ids_sorted(self) -> None:
        self.assertEqual(list_character_ids(), ["aurora", "kai"])

    def test_missing_pack_fails_loud(self) -> None:
        with self.assertRaises(CharacterError):
            load_character("does-not-exist")

    def test_id_mismatch_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack_dir = Path(directory) / "fake"
            pack_dir.mkdir()
            (pack_dir / "character.json").write_text(
                json.dumps(
                    {
                        "id": "other",
                        "display_name": "Fake",
                        "default_bg": "room",
                        "default_expression": "neutral",
                        "backgrounds": {"room": "bg/room.png"},
                        "expressions": {"neutral": "sprites/neutral.png"},
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "prompt.md").write_text("hi", encoding="utf-8")
            (pack_dir / "bg").mkdir()
            (pack_dir / "sprites").mkdir()
            (pack_dir / "bg" / "room.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (pack_dir / "sprites" / "neutral.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            with self.assertRaises(CharacterError):
                load_character("fake", root=directory)


if __name__ == "__main__":
    unittest.main()
