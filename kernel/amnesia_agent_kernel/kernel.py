"""Public session API for the kernel."""

import asyncio
import os
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import aclosing
from typing import Any

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel import workspace as workspace_api
from amnesia_agent_kernel.agent import agent_turn
from amnesia_agent_kernel.provider import validate_execution_policy, validate_provider_config
from amnesia_agent_kernel.types import ExecutionPolicy, ProviderConfig
from amnesia_agent_kernel.workspace import Workspace


class KernelSession:
    """A provider configuration, execution policy, and workspace session."""

    def __init__(
        self,
        provider: ProviderConfig,
        policy: ExecutionPolicy | None = None,
        workspace_root: str | os.PathLike[str] | None = None,
    ) -> None:
        validate_provider_config(provider)
        selected_policy = policy or ExecutionPolicy()
        validate_execution_policy(selected_policy)
        self.provider = provider.snapshot()
        self.policy = selected_policy
        # Workspace.__init__ always setup_or_repair's (idempotent empty-file ensure).
        # Frontends that want a strict open should call check_workspace first; if
        # not ok, call setup_or_repair_workspace or create_or_reset_workspace
        # before (or instead of) relying on init setup for UX alone.
        self._workspace = Workspace(workspace_root)
        self._turn_lock = asyncio.Lock()

    @staticmethod
    def check_workspace(root: str | os.PathLike[str] | None = None) -> bool:
        """Return True if ``root`` is a usable workspace directory.

        Resolves ``root`` via the same rules as session init (``None`` →
        ``~/.amnesia-agent``). OK only when the path exists as a directory and
        both ``system_prompt.md`` and ``memory.md`` exist as files (may be
        empty). ``history/`` may be missing. Does not validate history contents.

        Returns False for missing or invalid structure (frontend should offer
        repair vs reset). Does not raise for normal not-ok cases.
        """
        return workspace_api.check_workspace(root)

    @staticmethod
    def setup_or_repair_workspace(root: str | os.PathLike[str] | None = None) -> None:
        """Create missing workspace directory / empty prompt and memory files.

        Does not wipe existing content and does not delete ``history/``.
        """
        workspace_api.setup_or_repair_workspace(root)

    @staticmethod
    def create_or_reset_workspace(root: str | os.PathLike[str] | None = None) -> None:
        """Wipe ``root`` if it is a directory, then recreate empty prompt/memory.

        A missing root is treated as already clear. A non-directory path raises
        ``WorkspaceError``.
        """
        workspace_api.create_or_reset_workspace(root)

    async def turn(
        self,
        user_input: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> AsyncGenerator[str | AllMessageValues, None]:
        """Queue and stream one turn, optionally requesting structured output.

        Yields ``str`` deltas and ``AllMessageValues`` assistant/tool messages.
        """
        async with self._turn_lock:
            events = agent_turn(
                self.provider,
                self.policy,
                self._workspace,
                user_input,
                response_format,
            )
            async with aclosing(events):
                async for event in events:
                    yield event

    def read_system_prompt(self) -> str:
        return self._workspace.read_system_prompt()

    def update_system_prompt(self, content: str) -> None:
        self._workspace.update_system_prompt(content)

    def read_memory(self) -> str:
        return self._workspace.read_memory()

    def update_memory(self, content: str) -> None:
        self._workspace.update_memory(content)

    def read_history(self, date: str | None = None) -> list[AllMessageValues]:
        return self._workspace.read_history(date)

    def list_history(self) -> list[str]:
        return self._workspace.list_history()

    def update_history(self, messages: Sequence[AllMessageValues], date: str | None = None) -> None:
        self._workspace.update_history(messages, date)

    def reset_history(self) -> None:
        self._workspace.reset_history()
