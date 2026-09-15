import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amnesia_agent_kernel import KernelSession, ProviderConfig, WorkspaceError
from amnesia_agent_kernel.workspace import (
    Workspace,
    check_workspace,
    create_or_reset_workspace,
    create_workspace,
    setup_or_repair_workspace,
)


class WorkspaceLifecycleTests(unittest.TestCase):
    def fixed_clock(self):
        from datetime import datetime, timezone

        return datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    def _seed_workspace(self, directory: str, *, with_history: bool = True) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        (root / "system_prompt.md").write_text("prompt-keep", encoding="utf-8")
        (root / "memory.md").write_text("memory-keep", encoding="utf-8")
        if with_history:
            history = root / "history"
            history.mkdir()
            (history / "2026-08-28.jsonl").write_text(
                '{"role":"user","content":"hi"}\n', encoding="utf-8"
            )
        return root

    def test_check_workspace_ok_with_and_without_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with_history = self._seed_workspace(
                str(Path(directory) / "with-hist"), with_history=True
            )
            without_history = self._seed_workspace(
                str(Path(directory) / "no-hist"), with_history=False
            )
            self.assertTrue(check_workspace(with_history))
            self.assertTrue(KernelSession.check_workspace(with_history))
            self.assertTrue(check_workspace(without_history))
            self.assertTrue(KernelSession.check_workspace(without_history))
            # Empty files still OK
            (without_history / "system_prompt.md").write_text("", encoding="utf-8")
            (without_history / "memory.md").write_text("", encoding="utf-8")
            self.assertTrue(check_workspace(without_history))

    def test_check_workspace_false_for_missing_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            self.assertFalse(check_workspace(missing))
            self.assertFalse(KernelSession.check_workspace(missing))

            file_root = Path(directory) / "not-a-dir"
            file_root.write_text("x", encoding="utf-8")
            self.assertFalse(check_workspace(file_root))

            incomplete = Path(directory) / "incomplete"
            incomplete.mkdir()
            (incomplete / "system_prompt.md").write_text("p", encoding="utf-8")
            self.assertFalse(check_workspace(incomplete))

            (incomplete / "memory.md").mkdir()
            self.assertFalse(check_workspace(incomplete))

    def test_setup_or_repair_preserves_content_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            result = setup_or_repair_workspace(root)
            self.assertIsNone(result)
            self.assertEqual((root / "system_prompt.md").read_text(encoding="utf-8"), "prompt-keep")
            self.assertEqual((root / "memory.md").read_text(encoding="utf-8"), "memory-keep")
            self.assertTrue((root / "history" / "2026-08-28.jsonl").exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "new"
            KernelSession.setup_or_repair_workspace(root)
            self.assertTrue(root.is_dir())
            self.assertEqual((root / "system_prompt.md").read_text(encoding="utf-8"), "")
            self.assertEqual((root / "memory.md").read_text(encoding="utf-8"), "")
            self.assertFalse((root / "history").exists())
            self.assertTrue(check_workspace(root))

    def test_create_or_reset_hard_wipes_prompt_memory_history_and_extras(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            extra = root / "notes.txt"
            extra.write_text("wipe-me", encoding="utf-8")
            nested = root / "assets" / "image.png"
            nested.parent.mkdir()
            nested.write_bytes(b"png")

            result = create_or_reset_workspace(root)
            self.assertIsNone(result)
            self.assertEqual((root / "system_prompt.md").read_text(encoding="utf-8"), "")
            self.assertEqual((root / "memory.md").read_text(encoding="utf-8"), "")
            self.assertFalse((root / "history").exists())
            self.assertFalse(extra.exists())
            self.assertFalse(nested.exists())
            self.assertFalse((root / "assets").exists())
            self.assertTrue(check_workspace(root))

        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "was-missing"
            KernelSession.create_or_reset_workspace(missing)
            self.assertTrue(missing.is_dir())
            self.assertEqual((missing / "system_prompt.md").read_text(encoding="utf-8"), "")
            self.assertEqual((missing / "memory.md").read_text(encoding="utf-8"), "")

    def test_create_workspace_allows_missing_or_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "fresh"
            create_workspace(missing)
            self.assertTrue(missing.is_dir())
            self.assertEqual((missing / "system_prompt.md").read_text(encoding="utf-8"), "")
            self.assertEqual((missing / "memory.md").read_text(encoding="utf-8"), "")
            self.assertTrue(check_workspace(missing))

        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty"
            empty.mkdir()
            KernelSession.create_workspace(empty)
            self.assertEqual((empty / "system_prompt.md").read_text(encoding="utf-8"), "")
            self.assertEqual((empty / "memory.md").read_text(encoding="utf-8"), "")
            self.assertTrue(check_workspace(empty))

    def test_create_workspace_refuses_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            with self.assertRaises(WorkspaceError):
                create_workspace(root)
            with self.assertRaises(WorkspaceError):
                KernelSession.create_workspace(root)
            # Non-empty content must survive a refused create.
            self.assertEqual((root / "system_prompt.md").read_text(encoding="utf-8"), "prompt-keep")
            self.assertEqual((root / "memory.md").read_text(encoding="utf-8"), "memory-keep")
            self.assertTrue((root / "history" / "2026-08-28.jsonl").exists())

    def test_create_or_reset_rejects_non_directory_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_root = Path(directory) / "not-a-dir"
            file_root.write_text("x", encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                create_or_reset_workspace(file_root)
            with self.assertRaises(WorkspaceError):
                KernelSession.create_or_reset_workspace(file_root)

    def test_workspace_init_setup_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            workspace = Workspace(root, clock=self.fixed_clock)
            self.assertEqual(workspace.read_system_prompt(), "prompt-keep")
            self.assertEqual(workspace.read_memory(), "memory-keep")
            self.assertEqual(workspace.list_history(), ["2026-08-28"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing-open"
            workspace = Workspace(root)
            self.assertTrue(root.is_dir())
            self.assertEqual(workspace.read_system_prompt(), "")
            self.assertEqual(workspace.read_memory(), "")
            self.assertEqual(workspace.list_history(), [])

    def test_kernel_session_init_without_mode(self) -> None:
        def make_session(root: str) -> KernelSession:
            with patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value={"keys_in_environment": True},
            ):
                return KernelSession(
                    ProviderConfig(model="openai/test"),
                    workspace_root=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            self.assertTrue(KernelSession.check_workspace(root))
            session = make_session(str(root))
            self.assertEqual(session.read_system_prompt(), "prompt-keep")
            self.assertEqual(session.read_memory(), "memory-keep")
            self.assertEqual(session.list_history(), ["2026-08-28"])

            KernelSession.create_or_reset_workspace(root)
            session = make_session(str(root))
            self.assertEqual(session.read_system_prompt(), "")
            self.assertEqual(session.read_memory(), "")
            self.assertEqual(session.list_history(), [])


if __name__ == "__main__":
    unittest.main()
