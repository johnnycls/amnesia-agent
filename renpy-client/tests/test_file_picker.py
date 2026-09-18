"""Tests for the picker seam and picker-owned cleanup."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from file_picker import (  # noqa: E402
    DesktopPickerAdapter,
    FilePicker,
    PickerResult,
    cleanup_staged_file,
)


class _FakeAdapter:
    def __init__(self, result: PickerResult) -> None:
        self.result = result

    def pick_one(self, callback) -> None:
        callback(self.result)


class FilePickerTests(unittest.TestCase):
    def test_adapter_is_replaceable_and_completes_once(self) -> None:
        result = PickerResult(cancelled=True)
        received: list[PickerResult] = []

        FilePicker(adapter=_FakeAdapter(result)).pick_one(received.append)

        self.assertEqual(received, [result])

    def test_cleanup_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "picked.amod"
            path.write_bytes(b"fixture")

            cleanup_staged_file(path)
            cleanup_staged_file(path)

            self.assertFalse(path.exists())

    def test_desktop_picker_rejects_multiple_selection_result(self) -> None:
        # The adapter checks the native tinyfiledialogs separator even though
        # it requests single selection, protecting the one-file invariant.
        import types

        old_renpy = sys.modules.get("renpy")
        fake_renpy = types.SimpleNamespace(
            tfd=types.SimpleNamespace(
                openFileDialog=lambda *args: "one.amod|two.amod",
            )
        )
        sys.modules["renpy"] = fake_renpy
        try:
            received: list[PickerResult] = []
            DesktopPickerAdapter().pick_one(received.append)
            self.assertEqual(received[0].error, "Select exactly one .amod file.")
        finally:
            if old_renpy is None:
                sys.modules.pop("renpy", None)
            else:
                sys.modules["renpy"] = old_renpy


if __name__ == "__main__":
    unittest.main()
