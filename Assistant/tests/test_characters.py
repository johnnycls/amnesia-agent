"""Character animation-pack loader tests (no Ren'Py)."""

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
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name == "nt":
            raise unittest.SkipTest(f"symlinks unavailable: {error}") from error
        raise


def create_asset(root: Path, kind: str, name: str, frames: int = 1) -> None:
    directory = root / kind / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "animation.json").write_text(
        json.dumps({"type": "png_sequence", "fps": 8, "loop": True}),
        encoding="utf-8",
    )
    for index in range(1, frames + 1):
        (directory / f"{index:04d}.png").write_bytes(TRANSPARENT_PNG)


def create_pack(root: Path, name: str = "fake") -> Path:
    pack = root / name
    (pack / "bg").mkdir(parents=True)
    (pack / "expressions").mkdir()
    (pack / "character.json").write_text(
        json.dumps({"id": name, "display_name": "Fake", "default_bg": "room"}),
        encoding="utf-8",
    )
    (pack / "prompt.md").write_text("hi", encoding="utf-8")
    create_asset(pack, "bg", "room")
    create_asset(pack, "expressions", "neutral")
    create_asset(pack, "expressions", "busy")
    return pack


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
            for asset in list(pack.backgrounds.values()) + list(pack.expressions.values()):
                self.assertEqual(len(asset.frames), 1)
                self.assertTrue(Path(asset.path).is_file(), asset.path)
            self.assertIsNotNone(pack.portrait_path())

    def test_list_character_ids_sorted(self) -> None:
        self.assertEqual(list_character_ids(), ["aurora", "kai"])

    def test_missing_pack_fails_loud(self) -> None:
        with self.assertRaises(CharacterError):
            load_character("does-not-exist")

    def test_invalid_metadata_encoding_fails_as_character_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = create_pack(Path(directory))
            (pack / "character.json").write_bytes(b"{\xff")
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("character.json", str(context.exception))

    def test_animation_frames_and_metadata_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = create_pack(Path(directory))
            create_asset(pack, "expressions", "smile", frames=2)
            animation = load_character("fake", root=directory).expressions["smile"]
            self.assertEqual(animation.kind, "animation")
            self.assertEqual(len(animation.frames), 2)
            self.assertEqual(animation.fps, 8.0)

    def test_frame_number_gaps_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = create_pack(Path(directory))
            animation = pack / "expressions" / "neutral"
            (animation / "0001.png").unlink()
            (animation / "0002.png").write_bytes(TRANSPARENT_PNG)
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("consecutive", str(context.exception))

    def test_static_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = create_pack(Path(directory))
            (pack / "bg" / "bad.png").write_bytes(TRANSPARENT_PNG)
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("animation directory", str(context.exception))

    def test_asset_outside_pack_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = create_pack(root)
            outside = root / "outside.png"
            outside.write_bytes(TRANSPARENT_PNG)
            frame = pack / "expressions" / "neutral" / "0001.png"
            frame.unlink()
            symlink_or_skip(frame, outside)
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("escapes character pack", str(context.exception))

    def test_unsupported_video_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = create_pack(Path(directory))
            (pack / "bg" / "loop.webm").write_bytes(b"RIFF")
            with self.assertRaises(CharacterError) as context:
                load_character("fake", root=directory)
            self.assertIn("animation directory", str(context.exception))

    def test_id_mismatch_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = create_pack(Path(directory))
            (pack / "character.json").write_text(
                json.dumps({"id": "other", "display_name": "Fake", "default_bg": "room"}),
                encoding="utf-8",
            )
            with self.assertRaises(CharacterError):
                load_character("fake", root=directory)


if __name__ == "__main__":
    unittest.main()
