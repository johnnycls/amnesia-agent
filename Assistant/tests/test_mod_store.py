"""Safe .amod lifecycle tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from characters.loader import load_character  # noqa: E402
from characters.mod_store import ModStore  # noqa: E402


class ModStoreTests(unittest.TestCase):
    def _archive(
        self,
        inbox: Path,
        *,
        mod_id: str = "creator.character",
        version: str = "1.0.0",
        extra: dict[str, str] | None = None,
    ) -> Path:
        source = Path(tempfile.mkdtemp())
        (source / "bg" / "room").mkdir(parents=True)
        (source / "expressions" / "neutral").mkdir(parents=True)
        (source / "expressions" / "busy").mkdir(parents=True)
        (source / "character.json").write_text(
            json.dumps({"id": mod_id, "display_name": "Community", "default_bg": "room"}),
            encoding="utf-8",
        )
        (source / "prompt.md").write_text("A community character.", encoding="utf-8")
        animation = json.dumps({"type": "png_sequence", "fps": 8, "loop": True})
        for directory in (
            source / "bg" / "room",
            source / "expressions" / "neutral",
            source / "expressions" / "busy",
        ):
            (directory / "animation.json").write_text(animation, encoding="utf-8")
            (directory / "0001.png").write_bytes(
                b"\x89PNG\r\n\x1a\n"
                b"\x00\x00\x00\x0dIHDR"
                b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
                b"\x00\x00\x00\x00IEND\xaeB`\x82"
            )
        manifest = {
            "format": "amnesia-character",
            "schema_version": 1,
            "id": mod_id,
            "version": version,
            "display_name": "Community",
        }
        destination = inbox / f"{mod_id.replace('.', '-')}-{version}.amod"
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for path in source.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(source).as_posix())
            for name, content in (extra or {}).items():
                archive.writestr(name, content)
        return destination

    def test_install_removes_valid_archive_and_loads_pack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            archive = self._archive(inbox)
            store = ModStore(root)

            results = store.install_inbox()

            self.assertTrue(results[0].installed)
            self.assertFalse(archive.exists())
            pack = load_character(
                "creator.character", root=store.installed, source="mod", version="1.0.0"
            )
            self.assertEqual(pack.source, "mod")

    def test_invalid_archive_stays_in_inbox_with_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            archive = inbox / "bad.amod"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape.txt", "no")
            store = ModStore(root)

            results = store.install_inbox()

            self.assertFalse(results[0].installed)
            self.assertTrue(archive.exists())
            self.assertTrue(archive.with_suffix(".amod.error.txt").exists())

    def test_highest_valid_semantic_version_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            old = self._archive(inbox, version="1.9.0")
            new = self._archive(inbox, version="1.10.0")
            store = ModStore(root)

            store.install_inbox()

            self.assertFalse(old.exists())
            self.assertFalse(new.exists())
            self.assertEqual(
                store.installed_manifests()["creator.character"].version, "1.10.0"
            )

    def test_bundled_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            archive = self._archive(inbox, mod_id="aurora")
            store = ModStore(root)

            results = store.install_inbox(reserved_ids={"aurora"})

            self.assertFalse(results[0].installed)
            self.assertTrue(archive.exists())
            self.assertFalse((store.installed / "aurora").exists())


if __name__ == "__main__":
    unittest.main()
