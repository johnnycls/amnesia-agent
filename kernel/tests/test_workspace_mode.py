import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amnesia_agent_kernel import ConfigError, KernelSession, ProviderConfig, WorkspaceError
from amnesia_agent_kernel.workspace import Workspace


class WorkspaceModeTests(unittest.TestCase):
    def fixed_clock(self):
        from datetime import datetime, timezone

        return datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    def _seed_workspace(self, directory: str) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        (root / "system_prompt.md").write_text("prompt-keep", encoding="utf-8")
        (root / "memory.md").write_text("memory-keep", encoding="utf-8")
        history = root / "history"
        history.mkdir()
        (history / "2026-08-28.jsonl").write_text(
            '{"role":"user","content":"hi"}\n', encoding="utf-8"
        )
        return root

    def test_open_default_preserves_existing_and_creates_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            workspace = Workspace(root, clock=self.fixed_clock)
            self.assertEqual(workspace.read_system_prompt(), "prompt-keep")
            self.assertEqual(workspace.read_memory(), "memory-keep")
            self.assertEqual(workspace.list_history(), ["2026-08-28"])
            self.assertEqual(
                workspace.read_history(),
                [{"role": "user", "content": "hi"}],
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing-open"
            workspace = Workspace(root, mode="open")
            self.assertTrue(root.is_dir())
            self.assertEqual(workspace.read_system_prompt(), "")
            self.assertEqual(workspace.read_memory(), "")
            self.assertEqual(workspace.list_history(), [])

    def test_create_wipes_existing_then_empty_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            workspace = Workspace(root, clock=self.fixed_clock, mode="create")
            self.assertEqual(workspace.read_system_prompt(), "")
            self.assertEqual(workspace.read_memory(), "")
            self.assertEqual(workspace.list_history(), [])
            self.assertFalse((root / "history").exists())
            self.assertEqual((root / "system_prompt.md").read_text(encoding="utf-8"), "")
            self.assertEqual((root / "memory.md").read_text(encoding="utf-8"), "")

    def test_reset_workspace_wipes_and_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            workspace = Workspace(root, clock=self.fixed_clock, mode="open")
            result = workspace.reset_workspace()
            self.assertIsNone(result)
            self.assertEqual(workspace.read_system_prompt(), "")
            self.assertEqual(workspace.read_memory(), "")
            self.assertEqual(workspace.list_history(), [])
            self.assertFalse((root / "history").exists())

    def test_missing_root_open_and_create_yield_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            open_root = Path(directory) / "open-missing"
            create_root = Path(directory) / "create-missing"
            opened = Workspace(open_root, mode="open")
            created = Workspace(create_root, mode="create")
            for workspace, root in ((opened, open_root), (created, create_root)):
                with self.subTest(root=str(root)):
                    self.assertTrue(root.is_dir())
                    self.assertEqual(workspace.read_system_prompt(), "")
                    self.assertEqual(workspace.read_memory(), "")
                    self.assertEqual(workspace.list_history(), [])

    def test_invalid_workspace_mode_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                Workspace(directory, mode="wipe")  # type: ignore[arg-type]

    def test_reset_workspace_rejects_non_directory_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_root = Path(directory) / "not-a-dir"
            file_root.write_text("x", encoding="utf-8")
            workspace = Workspace.__new__(Workspace)
            workspace.root = file_root
            from amnesia_agent_kernel.workspace.history import HistoryStore

            workspace._history = HistoryStore(file_root, self.fixed_clock)
            with self.assertRaises(WorkspaceError):
                workspace.reset_workspace()

    def test_kernel_session_open_create_and_reset(self) -> None:
        def make_session(root: str, mode: str = "open") -> KernelSession:
            with patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value={"keys_in_environment": True},
            ):
                return KernelSession(
                    ProviderConfig(model="openai/test"),
                    workspace_root=root,
                    workspace_mode=mode,  # type: ignore[arg-type]
                )

        with tempfile.TemporaryDirectory() as directory:
            root = self._seed_workspace(directory)
            session = make_session(str(root), "open")
            self.assertEqual(session.read_system_prompt(), "prompt-keep")
            self.assertEqual(session.read_memory(), "memory-keep")
            self.assertEqual(session.list_history(), ["2026-08-28"])

            session = make_session(str(root), "create")
            self.assertEqual(session.read_system_prompt(), "")
            self.assertEqual(session.read_memory(), "")
            self.assertEqual(session.list_history(), [])

            session.update_system_prompt("again")
            session.update_memory("again")
            session.update_history([{"role": "user", "content": "x"}])
            result = session.reset_workspace()
            self.assertIsNone(result)
            self.assertEqual(session.read_system_prompt(), "")
            self.assertEqual(session.read_memory(), "")
            self.assertEqual(session.list_history(), [])

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                make_session(directory, "nope")


if __name__ == "__main__":
    unittest.main()
