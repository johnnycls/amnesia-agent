import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from home_config.store import (
    ConfigError,
    RenpyConfigStore,
    default_config_dict,
)


class RenpyConfigStoreTests(unittest.TestCase):
    def test_missing_file_lazy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RenpyConfigStore(directory)
            config = store.load()
            self.assertEqual(config.language, "english")
            self.assertEqual(config.recent_workspaces, ())
            self.assertTrue(store.path.is_file())
            self.assertEqual(
                json.loads(store.path.read_text(encoding="utf-8")),
                default_config_dict(),
            )

    def test_corrupt_json_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RenpyConfigStore(directory)
            store.path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                store.load()

    def test_unexpected_property_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RenpyConfigStore(directory)
            store.path.write_text(
                json.dumps(
                    {"language": "english", "recent_workspaces": [], "extra": 1}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                store.load()

    def test_bump_recent_sorts_descending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RenpyConfigStore(directory)
            store.load()
            store.bump_recent("/tmp/a")
            store.bump_recent("/tmp/b")
            config = store.load()
            paths = [Path(e.path) for e in config.recent_workspaces]
            self.assertEqual(paths[0], Path("/tmp/b").resolve())
            self.assertIn(Path("/tmp/a").resolve(), paths)

    def test_no_separate_last_workspace_key(self) -> None:
        raw = default_config_dict()
        self.assertNotIn("last_workspace", raw)
        self.assertEqual(set(raw), {"language", "recent_workspaces"})

    @unittest.skipIf(
        os.name == "nt",
        "NTFS ignores POSIX 0o600; st_mode & 0o777 stays 0o666 on Windows",
    )
    def test_atomic_write_sets_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RenpyConfigStore(directory)
            store.write_defaults()
            mode = store.path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
