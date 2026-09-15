import gc
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from amnesia_agent_kernel.errors import AgentError
from amnesia_agent_kernel.workspace import Workspace
from amnesia_agent_kernel.workspace.history import HistoryStore
from amnesia_agent_kernel.workspace.paths import resolve_root


class HistoryTests(unittest.TestCase):
    def fixed_clock(self) -> datetime:
        return datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    @property
    def expected_timestamp(self) -> str:
        return "2026-08-28T12:00:00+00:00"

    def test_history_is_partitioned_by_utc_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            workspace.append_history({"role": "user", "content": "hi"})
            workspace.update_history([{"role": "assistant", "content": "older"}], date="2026-08-27")

            self.assertEqual(workspace.list_history(), ["2026-08-28", "2026-08-27"])
            self.assertEqual(
                workspace.read_history(),
                [
                    {
                        "role": "user",
                        "content": "hi",
                        "timestamp": self.expected_timestamp,
                    }
                ],
            )
            self.assertEqual(
                workspace.read_history("2026-08-27"),
                [
                    {
                        "role": "assistant",
                        "content": "older",
                        "timestamp": self.expected_timestamp,
                    }
                ],
            )
            self.assertTrue(Path(directory, "history", "2026-08-28.jsonl").exists())

    def test_append_uses_utc_date_for_timezone_aware_clock(self) -> None:
        def local_clock() -> datetime:
            return datetime(2026, 8, 27, 23, 30, tzinfo=timezone(timedelta(hours=-1)))

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=local_clock)
            workspace.append_history({"role": "user", "content": "utc"})
            self.assertEqual(workspace.list_history(), ["2026-08-28"])

    def test_list_history_ignores_non_date_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_dir = Path(directory, "history")
            history_dir.mkdir()
            (history_dir / "notes.jsonl").write_text("", encoding="utf-8")
            (history_dir / "2026-02-30.jsonl").write_text("", encoding="utf-8")
            (history_dir / "2026-08-28.jsonl").write_text("", encoding="utf-8")
            workspace = Workspace(directory, clock=self.fixed_clock)
            self.assertEqual(workspace.list_history(), ["2026-08-28"])

    def test_read_history_returns_empty_for_missing_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            self.assertEqual(workspace.read_history(), [])
            self.assertEqual(workspace.read_history("2026-08-27"), [])

    def test_update_history_defaults_to_today_and_empty_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            workspace.update_history([{"role": "assistant", "content": "ok"}])
            day_path = Path(directory, "history", "2026-08-28.jsonl")
            self.assertTrue(day_path.exists())
            workspace.update_history([], date="2026-08-28")
            self.assertEqual(workspace.list_history(), [])
            self.assertFalse(day_path.exists())
            self.assertFalse(Path(directory, "history").exists())

    def test_empty_update_history_deletes_day_file_and_list_entry(self) -> None:
        """Delete-day path: update_history([], date=...) unlinks the jsonl entirely."""
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            workspace.update_history([{"role": "user", "content": "keep"}], date="2026-08-27")
            workspace.update_history([{"role": "user", "content": "drop"}], date="2026-08-26")
            drop_path = Path(directory, "history", "2026-08-26.jsonl")
            keep_path = Path(directory, "history", "2026-08-27.jsonl")
            self.assertTrue(drop_path.exists())

            workspace.update_history([], date="2026-08-26")

            self.assertFalse(drop_path.exists())
            self.assertTrue(keep_path.exists())
            self.assertEqual(workspace.list_history(), ["2026-08-27"])
            self.assertEqual(workspace.read_history("2026-08-26"), [])

    def test_append_history_does_not_mutate_input_and_persists_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            original = {"role": "user", "content": "hi"}
            workspace.append_history(original)
            self.assertEqual(original, {"role": "user", "content": "hi"})
            self.assertNotIn("timestamp", original)

            day_path = Path(directory, "history", "2026-08-28.jsonl")
            line = json.loads(day_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(line["role"], "user")
            self.assertEqual(line["content"], "hi")
            self.assertEqual(line["timestamp"], self.expected_timestamp)
            self.assertEqual(
                workspace.read_history(),
                [
                    {
                        "role": "user",
                        "content": "hi",
                        "timestamp": self.expected_timestamp,
                    }
                ],
            )

    def test_update_history_stamps_copies_without_mutating_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            messages = [{"role": "assistant", "content": "ok"}]
            workspace.update_history(messages, date="2026-08-27")
            self.assertEqual(messages, [{"role": "assistant", "content": "ok"}])
            self.assertNotIn("timestamp", messages[0])
            self.assertEqual(
                workspace.read_history("2026-08-27"),
                [
                    {
                        "role": "assistant",
                        "content": "ok",
                        "timestamp": self.expected_timestamp,
                    }
                ],
            )

    def test_legacy_lines_without_timestamp_still_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_dir = Path(directory, "history")
            history_dir.mkdir()
            (history_dir / "2026-08-28.jsonl").write_text(
                '{"role":"user","content":"legacy"}\n', encoding="utf-8"
            )
            workspace = Workspace(directory, clock=self.fixed_clock)
            self.assertEqual(
                workspace.read_history("2026-08-28"),
                [{"role": "user", "content": "legacy"}],
            )

    def test_reset_history_removes_all_daily_files_but_ignores_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            legacy = Path(directory, "history.jsonl")
            legacy.write_text('{"role":"user","content":"legacy"}\n', encoding="utf-8")
            workspace.update_history([{"role": "user", "content": "new"}])
            workspace.update_history([{"role": "user", "content": "old"}], date="2026-08-27")
            history_dir = Path(directory, "history")
            (history_dir / "junk.txt").write_text("noise", encoding="utf-8")

            workspace.reset_history()

            self.assertEqual(workspace.list_history(), [])
            self.assertEqual(json.loads(legacy.read_text(encoding="utf-8"))["content"], "legacy")
            self.assertEqual(workspace.read_history(), [])
            self.assertFalse(history_dir.exists())

    def test_invalid_dates_raise_agent_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            for invalid in ("2026-2-08", "2026-02-30", "../2026-02-08"):
                with self.subTest(invalid=invalid), self.assertRaises(AgentError):
                    workspace.read_history(invalid)

    def test_legacy_history_is_not_seeded_or_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory, clock=self.fixed_clock)
            Path(directory, "history.jsonl").write_text(
                '{"role":"user","content":"legacy"}\n', encoding="utf-8"
            )
            self.assertEqual(workspace.read_history(), [])
            self.assertEqual(workspace.list_history(), [])

    def test_history_lock_registry_releases_when_unused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = resolve_root(directory)
            key = os.path.normcase(str(root))
            workspace = Workspace(directory, clock=self.fixed_clock)
            self.assertIn(key, HistoryStore._lock_registry)
            del workspace
            gc.collect()
            self.assertNotIn(key, HistoryStore._lock_registry)

    def test_symlink_and_realpath_share_history_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            link.symlink_to(real)
            ws_real = Workspace(real, clock=self.fixed_clock)
            ws_link = Workspace(link, clock=self.fixed_clock)
            self.assertIs(ws_real._history._history_lock, ws_link._history._history_lock)


if __name__ == "__main__":
    unittest.main()
