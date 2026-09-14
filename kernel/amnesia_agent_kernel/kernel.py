"""Public session API for the kernel."""

import asyncio
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.agent import agent_turn
from amnesia_agent_kernel.events import Event
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
        self._workspace = Workspace(workspace_root)
        self._turn_lock = asyncio.Lock()

    async def turn(
        self,
        user_input: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        """Queue and stream one turn, optionally requesting structured output."""
        async with self._turn_lock:
            async for event in agent_turn(
                self.provider,
                self.policy,
                self._workspace,
                user_input,
                response_format,
            ):
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

    def update_history(
        self, messages: Sequence[AllMessageValues], date: str | None = None
    ) -> None:
        self._workspace.update_history(messages, date)

    def reset_history(self) -> None:
        self._workspace.reset_history()
