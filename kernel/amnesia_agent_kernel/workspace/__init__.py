"""Kernel-owned persistent workspace state."""

import os
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.workspace import files as workspace_files
from amnesia_agent_kernel.workspace.history import HistoryStore
from amnesia_agent_kernel.workspace.paths import resolve_root


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
        self.setup()

    def setup(self) -> None:
        """Create the workspace and empty kernel-owned files when missing."""
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
