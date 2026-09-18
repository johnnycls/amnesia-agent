"""Safe one-file .amod lifecycle tests."""

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
        destination: Path,
        *,
        mod_id: str = "creator.character",
        version: str = "1.0.0",
        extra: dict[str, str] | None = None,
    ) -> Path:
        source = Path(tempfile.mkdtemp())
        (source / "bg" / "room").mkdir(parents=True)
        (source / "expressions" / "neutral").mkdir(parents=True)
        (source / "expressions" / "busy").mkdir(parents=True)
        (source / "bgm").mkdir(parents=True)
        (source / "bgm" / "default.ogg").write_bytes(b"OggS\x00fixture")
        (source / "character.json").write_text(
            json.dumps(
                {
                    "id": mod_id,
                    "display_name": "Community",
                    "default_bg": "room",
                    "version": version,
                }
            ),
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
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for path in source.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(source).as_posix())
            for name, content in (extra or {}).items():
                archive.writestr(name, content)
        return destination

    def test_startup_cleanup_removes_partial_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "mods"
            stale = root / ".staging" / "partial" / "nested"
            stale.mkdir(parents=True)
            (stale / "archive.amod").write_bytes(b"stale")

            store = ModStore(root)
            store.clear_staging()

            self.assertEqual(list(store.staging.iterdir()), [])

    def test_install_selected_archive_cleans_staging_and_loads_pack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            archive = self._archive(store.staging / "picked.amod")

            result = store.install_selected_archive(archive)

            self.assertTrue(result.installed)
            self.assertTrue(result.clean)
            self.assertFalse(archive.exists())
            self.assertFalse(list(store.staging.iterdir()))
            pack = load_character(
                "creator.character", root=store.installed, source="mod", version="1.0.0"
            )
            self.assertEqual(pack.source, "mod")

    def test_bgm_directory_is_allowed_in_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            archive = self._archive(store.staging / "picked.amod")

            result = store.install_selected_archive(archive)

            self.assertTrue(result.installed)
            self.assertTrue(
                (store.installed / "creator.character" / "bgm" / "default.ogg").is_file()
            )

    def test_invalid_archive_is_consumed_without_error_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            archive = store.staging / "bad.amod"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape.txt", "no")

            result = store.install_selected_archive(archive)

            self.assertFalse(result.installed)
            self.assertTrue(result.error)
            self.assertTrue(result.clean)
            self.assertFalse(archive.exists())
            self.assertFalse(archive.with_suffix(".amod.error.txt").exists())

    def test_archive_outside_staging_is_rejected_without_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ModStore(root / "mods")
            archive = self._archive(root / "outside.amod")

            result = store.install_selected_archive(archive)

            self.assertFalse(result.installed)
            self.assertIn("outside the import staging", result.error)
            self.assertTrue(archive.exists())

    def test_older_archive_is_noop_and_preserves_newer_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            newer = self._archive(store.staging / "new.amod", version="1.10.0")
            self.assertTrue(store.install_selected_archive(newer).installed)
            older = self._archive(store.staging / "old.amod", version="1.9.0")

            result = store.install_selected_archive(older)

            self.assertFalse(result.installed)
            self.assertEqual(result.note, "superseded by installed 1.10.0")
            self.assertEqual(
                store.installed_manifests()["creator.character"].version, "1.10.0"
            )

    def test_cleanup_failure_is_reported_without_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            archive = self._archive(store.staging / "picked.amod")

            def fail_cleanup() -> None:
                raise OSError("staging is locked")

            store._clear_staging_unlocked = fail_cleanup  # type: ignore[method-assign]
            result = store.install_selected_archive(archive)

            self.assertTrue(result.installed)
            self.assertFalse(result.clean)
            self.assertIn("staging is locked", result.cleanup_error)
            self.assertTrue((store.installed / "creator.character").is_dir())

    def test_lock_is_reentrant_for_cleanup_and_import_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            with store._lock:
                store.clear_staging()
            self.assertEqual(list(store.staging.iterdir()), [])

    def test_bundled_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModStore(Path(directory) / "mods")
            archive = self._archive(store.staging / "picked.amod", mod_id="aurora")

            result = store.install_selected_archive(archive, reserved_ids={"aurora"})

            self.assertFalse(result.installed)
            self.assertIn("conflicts", result.error)
            self.assertTrue(result.clean)
            self.assertFalse((store.installed / "aurora").exists())


if __name__ == "__main__":
    unittest.main()
