"""Kernel-owned persistent workspace state."""

import os
import shutil
import stat
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import ConfigError, WorkspaceError
from amnesia_agent_kernel.workspace import files as workspace_files
from amnesia_agent_kernel.workspace.history import HistoryStore
from amnesia_agent_kernel.workspace.paths import resolve_root

WorkspaceMode = Literal["open", "create"]


class Workspace:
    """Persistent kernel state, excluding frontend-owned configuration."""

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        clock: Callable[[], datetime] | None = None,
        mode: WorkspaceMode = "open",
    ) -> None:
        if mode not in ("open", "create"):
            raise ConfigError(
                f"Invalid workspace mode {mode!r}; expected 'open' or 'create'"
            )
        self.root: Path = resolve_root(root)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._history = HistoryStore(self.root, self._clock)
        if mode == "create":
            self.reset_workspace()
        else:
            self.setup()

    def setup(self) -> None:
        """Create the workspace and empty kernel-owned files when missing."""
        workspace_files.setup_workspace_files(self.root)

    def reset_workspace(self) -> None:
        """Remove the workspace root, then recreate empty prompt and memory files.

        If the root path is missing, it is treated as already clear. If the path
        exists but is not a directory, raises ``WorkspaceError``. After
        ``shutil.rmtree``, ``HistoryStore`` still points at the same root
        ``Path``; ``setup`` recreates the directory and files.
        """
        with self._history._history_lock:
            try:
                try:
                    root_mode = self.root.stat().st_mode
                except FileNotFoundError:
                    pass
                else:
                    if not stat.S_ISDIR(root_mode):
                        raise WorkspaceError(
                            f"Workspace root is not a directory: {self.root}",
                            path=str(self.root),
                        )
                    shutil.rmtree(self.root)
            except WorkspaceError:
                raise
            except OSError as e:
                raise WorkspaceError(
                    f"Cannot reset workspace {self.root}: {e}",
                    path=str(self.root),
                ) from e
            workspace_files.setup_workspace_files(self.root)

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

    def update_history(
        self, messages: Sequence[AllMessageValues], date: str | None = None
    ) -> None:
        self._history.update_history(messages, date)

    def append_history(self, message: AllMessageValues) -> None:
        self._history.append_history(message)

    def reset_history(self) -> None:
        self._history.reset_history()
