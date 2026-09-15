"""Kernel-owned persistent workspace state."""

import os
import shutil
import stat
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import WorkspaceError
from amnesia_agent_kernel.workspace import files as workspace_files
from amnesia_agent_kernel.workspace.history import HistoryStore
from amnesia_agent_kernel.workspace.paths import resolve_root


def check_workspace(root: str | os.PathLike[str] | None = None) -> bool:
    """Return True if ``root`` looks like a usable workspace.

    OK when ``root`` exists as a directory and both ``system_prompt.md`` and
    ``memory.md`` exist as files (content may be empty). ``history/`` may be
    missing. Does not validate history JSONL contents.

    Returns False for missing/invalid structure (frontend should offer repair
    vs reset). Raises ``WorkspaceError`` only for unexpected OS errors.
    """
    path = resolve_root(root)
    try:
        if not path.is_dir():
            return False
        prompt = path / "system_prompt.md"
        memory = path / "memory.md"
        return prompt.is_file() and memory.is_file()
    except OSError as e:
        raise WorkspaceError(f"Cannot check workspace {path}: {e}", path=str(path)) from e


def setup_or_repair_workspace(root: str | os.PathLike[str] | None = None) -> None:
    """Create the workspace directory and empty prompt/memory files when missing.

    Does not wipe existing file content and does not delete ``history/``.
    """
    path = resolve_root(root)
    workspace_files.setup_workspace_files(path)


def create_workspace(root: str | os.PathLike[str] | None = None) -> None:
    """Create a workspace only when ``root`` is missing or an empty directory.

    - Missing root: create via ``setup_workspace_files`` (empty prompt/memory).
    - Existing empty directory: same setup (idempotent empty files).
    - Existing non-empty directory: raise ``WorkspaceError`` (do not wipe).
    - Existing non-directory: raise ``WorkspaceError``.
    """
    path = resolve_root(root)
    try:
        try:
            root_mode = path.stat().st_mode
        except FileNotFoundError:
            workspace_files.setup_workspace_files(path)
            return
        if not stat.S_ISDIR(root_mode):
            raise WorkspaceError(
                f"Workspace root is not a directory: {path}",
                path=str(path),
            )
        try:
            entries = list(path.iterdir())
        except OSError as e:
            raise WorkspaceError(
                f"Cannot inspect workspace {path}: {e}",
                path=str(path),
            ) from e
        if entries:
            raise WorkspaceError(
                f"Workspace root is not empty: {path}",
                path=str(path),
            )
    except WorkspaceError:
        raise
    except OSError as e:
        raise WorkspaceError(
            f"Cannot create workspace {path}: {e}",
            path=str(path),
        ) from e
    workspace_files.setup_workspace_files(path)


def create_or_reset_workspace(root: str | os.PathLike[str] | None = None) -> None:
    """Hard-reset a workspace: wipe the root directory, then empty prompt/memory.

    - Missing root: create via ``setup_workspace_files``.
    - Existing directory: ``rmtree`` the whole root, then setup empty
      ``system_prompt.md`` and ``memory.md``.
    - Existing non-directory: raise ``WorkspaceError``.
    """
    path = resolve_root(root)
    try:
        try:
            root_mode = path.stat().st_mode
        except FileNotFoundError:
            workspace_files.setup_workspace_files(path)
            return
        if not stat.S_ISDIR(root_mode):
            raise WorkspaceError(
                f"Workspace root is not a directory: {path}",
                path=str(path),
            )
        shutil.rmtree(path)
    except WorkspaceError:
        raise
    except OSError as e:
        raise WorkspaceError(
            f"Cannot reset workspace {path}: {e}",
            path=str(path),
        ) from e
    workspace_files.setup_workspace_files(path)


class Workspace:
    """Persistent kernel state, excluding frontend-owned configuration."""

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root: Path = resolve_root(root)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._history = HistoryStore(self.root, self._clock)
        # Lightweight open path: ensure empty files if missing (idempotent).
        # Frontends that want a strict open should call check_workspace first;
        # if not ok, call setup_or_repair_workspace, create_workspace, or
        # create_or_reset_workspace before relying on init setup alone for UX.
        self.setup()

    def setup(self) -> None:
        """Create the workspace and empty kernel-owned files when missing."""
        workspace_files.setup_workspace_files(self.root)

    def create(self) -> None:
        """Create under the history lock when missing or empty; refuse non-empty."""
        with self._history._history_lock:
            create_workspace(self.root)

    def create_or_reset(self) -> None:
        """Hard-reset under the history lock: wipe root, then empty prompt/memory."""
        with self._history._history_lock:
            create_or_reset_workspace(self.root)

    def read_system_prompt(self) -> str:
        return workspace_files.read_text(self.root, "system_prompt.md")

    def update_system_prompt(self, content: str) -> None:
        workspace_files.write_text(self.root, "system_prompt.md", content)

    def read_memory(self) -> str:
        return workspace_files.read_text(self.root, "memory.md")

    def update_memory(self, content: str) -> None:
        workspace_files.write_text(self.root, "memory.md", content)

    def list_history(self) -> list[str]:
        return self._history.list_history()

    def read_history(self, date: str | None = None) -> list[AllMessageValues]:
        return self._history.read_history(date)

    def update_history(self, messages: Sequence[AllMessageValues], date: str | None = None) -> None:
        self._history.update_history(messages, date)

    def append_history(self, message: AllMessageValues) -> None:
        self._history.append_history(message)

    def reset_history(self) -> None:
        self._history.reset_history()
