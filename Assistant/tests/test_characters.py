"""Character pack loader tests (no Ren'Py)."""

from __future__ import annotations

import json
import os
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

TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\x0dIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
)


def symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name == "nt":
            raise unittest.SkipTest(f"symlinks unavailable: {error}") from error
        raise


class CharacterPackTests(unittest.TestCase):
    def test_bundled_packs_load(self) -> None:
        packs = load_all_characters()
        ids = {p.id for p in packs}
        self.assertEqual(ids, {"aurora", "kai"})
        for pack in packs:
            self.assertTrue(pack.display_name)
            self.assertTrue(pack.prompt.strip())
            self.assertIn(pack.default_bg, pack.backgrounds)
            self.assertIn("neutral", pack.expressions)
            self.assertIn("busy", pack.expressions)
            for name in ("neutral", "smile", "think", "busy", "surprised", "sad", "shy"):
                self.assertIn(name, pack.expressions)
            for asset in pack.backgrounds.values():
                self.assertEqual(asset.kind, "image")
                self.assertTrue(Path(asset.path).is_file(), asset.path)
            for asset in pack.expressions.values():
                self.assertEqual(asset.kind, "image")
                self.assertTrue(Path(asset.path).is_file(), asset.path)
            self.assertIsNotNone(pack.portrait_path())

    def test_list_character_ids_sorted(self) -> None:
        self.assertEqual(list_character_ids(), ["aurora", "kai"])

    def test_missing_pack_fails_loud(self) -> None:
        with self.assertRaises(CharacterError):
            load_character("does-not-exist")

    def test_invalid_metadata_encoding_fails_as_character_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack_dir = Path(directory) / "fake"
            (pack_dir / "bg").mkdir(parents=True)
            (pack_dir / "expressions").mkdir()
            (pack_dir / "character.json").write_bytes(b"{\xff")
            (pack_dir / "prompt.md").write_text("hi", encoding="utf-8")
            (pack_dir / "bg" / "room.png").write_bytes(TRANSPARENT_PNG)
            (pack_dir / "expressions" / "neutral.png").write_bytes(
                TRANSPARENT_PNG
            )
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("character.json", str(context.exception))

    def test_duplicate_asset_stems_fail_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack_dir = Path(directory) / "fake"
            (pack_dir / "bg").mkdir(parents=True)
            (pack_dir / "expressions").mkdir()
            (pack_dir / "character.json").write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "display_name": "Fake",
                        "default_bg": "room",
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "prompt.md").write_text("hi", encoding="utf-8")
            (pack_dir / "bg" / "room.png").write_bytes(TRANSPARENT_PNG)
            (pack_dir / "expressions" / "neutral.png").write_bytes(
                TRANSPARENT_PNG
            )
            (pack_dir / "expressions" / "neutral.webp").write_bytes(
                b"RIFF0000WEBP"
            )
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("Duplicate expression id", str(context.exception))

    def test_asset_outside_pack_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack_dir = root / "fake"
            (pack_dir / "bg").mkdir(parents=True)
            (pack_dir / "expressions").mkdir()
            (root / "outside.png").write_bytes(TRANSPARENT_PNG)
            (pack_dir / "character.json").write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "display_name": "Fake",
                        "default_bg": "room",
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "prompt.md").write_text("hi", encoding="utf-8")
            (pack_dir / "bg" / "room.png").write_bytes(TRANSPARENT_PNG)
            symlink_or_skip(pack_dir / "expressions" / "neutral.png", root / "outside.png")
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("escapes character pack", str(context.exception))

    def test_video_assets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack_dir = Path(directory) / "fake"
            (pack_dir / "bg").mkdir(parents=True)
            (pack_dir / "expressions").mkdir()
            (pack_dir / "character.json").write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "display_name": "Fake",
                        "default_bg": "loop",
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "prompt.md").write_text("hi", encoding="utf-8")
            (pack_dir / "bg" / "loop.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom")
            for name in ("neutral", "busy"):
                (pack_dir / "expressions" / f"{name}.png").write_bytes(TRANSPARENT_PNG)

            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("Unsupported background format", str(context.exception))

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
                    }
                ),
                encoding="utf-8",
            )
            (pack_dir / "prompt.md").write_text("hi", encoding="utf-8")
            (pack_dir / "bg").mkdir()
            (pack_dir / "expressions").mkdir()
            (pack_dir / "bg" / "room.png").write_bytes(TRANSPARENT_PNG)
            (pack_dir / "expressions" / "neutral.png").write_bytes(
                TRANSPARENT_PNG
            )
            with self.assertRaises(CharacterError):
                load_character("fake", root=directory)


if __name__ == "__main__":
    unittest.main()
