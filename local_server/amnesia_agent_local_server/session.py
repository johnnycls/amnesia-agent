"""SessionManager: config-backed KernelSession construction and turn busy flag."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from typing import Any

from amnesia_agent_kernel import AgentError, ExecutionPolicy, KernelSession, ProviderConfig
from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_local_server.config import (
    ConfigStore,
    LoadedConfig,
    public_config,
    resolved_workspace_root,
)
from amnesia_agent_local_server.sse import event_envelope


class TurnBusyError(Exception):
    """Raised when an operation cannot run while a turn is active."""


class SessionManager:
    """Own config loading, fresh KernelSession construction, and the turn busy flag.

    Strategy A: do **not** cache ``KernelSession`` across turns. Every turn and
    every workspace read/update builds a new session from the latest config.
    """

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        instance_id: str | None = None,
    ) -> None:
        self.config_store = config_store or ConfigStore()
        self.instance_id = instance_id
        self.config_store.setup()
        self._active = False
        self._turn_events: AsyncIterator[Any] | None = None

    @property
    def active_turn(self) -> bool:
        return self._active

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "active_turn": self._active,
            "api_version": "v1",
            "instance_id": self.instance_id,
        }

    def require_idle(self, action: str) -> None:
        if self._active:
            raise TurnBusyError(f"Cannot {action} during an active turn")

    def _loaded(self) -> LoadedConfig:
        return self.config_store.load()

    def _workspace_root(self, loaded: LoadedConfig | None = None) -> str | None:
        return resolved_workspace_root(loaded if loaded is not None else self._loaded())

    def build_session(self, loaded: LoadedConfig | None = None) -> KernelSession:
        """Construct a fresh ``KernelSession`` from the latest (or given) config."""
        config = loaded if loaded is not None else self._loaded()
        return KernelSession(
            config.provider,
            config.policy,
            workspace_root=resolved_workspace_root(config),
        )

    def read_config(self) -> dict[str, Any]:
        return public_config(self.config_store.load())

    def update_config(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a partial config update; omit keys to keep current values."""
        self.require_idle("change configuration")
        current = self.config_store.load()
        updated = _merge_config(current, fields)
        self.config_store.save(updated)
        return public_config(updated)

    def reset_config(self) -> dict[str, Any]:
        self.require_idle("reset configuration")
        return public_config(self.config_store.reset())

    def check_workspace(self) -> bool:
        return KernelSession.check_workspace(self._workspace_root())

    def setup_or_repair_workspace(self) -> None:
        self.require_idle("setup or repair workspace")
        KernelSession.setup_or_repair_workspace(self._workspace_root())

    def create_or_reset_workspace(self) -> None:
        self.require_idle("create or reset workspace")
        KernelSession.create_or_reset_workspace(self._workspace_root())

    def read_system_prompt(self) -> str:
        return self.build_session().read_system_prompt()

    def update_system_prompt(self, content: str) -> str:
        self.require_idle("update system prompt")
        self.build_session().update_system_prompt(content)
        return content

    def read_memory(self) -> str:
        return self.build_session().read_memory()

    def update_memory(self, content: str) -> str:
        self.require_idle("update memory")
        self.build_session().update_memory(content)
        return content

    def list_history(self) -> list[str]:
        return self.build_session().list_history()

    def read_history(self, date: str | None = None) -> list[AllMessageValues]:
        return list(self.build_session().read_history(date))

    def update_history(
        self,
        messages: Sequence[AllMessageValues],
        date: str | None = None,
    ) -> None:
        self.require_idle("update history")
        self.build_session().update_history(messages, date)

    def reset_history(self) -> None:
        self.require_idle("reset history")
        self.build_session().reset_history()

    def start_turn(
        self,
        user_input: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Acquire the busy flag and return the SSE envelope stream.

        ``response_format`` is optional structured-output JSON passed through to
        ``KernelSession.turn`` (``None`` / omitted → no structured output).

        Raises ``TurnBusyError`` synchronously so callers can map it to HTTP 409
        before starting a streaming response. The caller must ``aclose`` the
        returned generator (e.g. via ``contextlib.aclosing``) so the busy flag
        is released on disconnect or cancel.
        """
        if self._active:
            raise TurnBusyError("Another turn is already active")
        self._active = True
        return self._stream_turn(user_input, response_format)

    async def _stream_turn(
        self,
        user_input: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE envelopes for one turn; release busy in ``finally``."""
        try:
            session = self.build_session()
            turn_events = session.turn(user_input, response_format=response_format)
            self._turn_events = turn_events
            try:
                async with aclosing(turn_events):
                    async for event in turn_events:
                        yield event_envelope(event)
                    yield {"type": "done", "data": {}}
            except AgentError as error:
                yield {
                    "type": "error",
                    "data": {"error_type": type(error).__name__, "message": str(error)},
                }
            except ValueError as error:
                yield {
                    "type": "error",
                    "data": {"error_type": "ServerError", "message": str(error)},
                }
        finally:
            self._turn_events = None
            self._active = False

    async def cancel_active_turn(self) -> None:
        """Best-effort aclose of the in-flight kernel turn iterator, if any."""
        turn_events = self._turn_events
        if turn_events is not None:
            aclose = getattr(turn_events, "aclose", None)
            if callable(aclose):
                await aclose()


def _merge_config(current: LoadedConfig, fields: Mapping[str, Any]) -> LoadedConfig:
    model = fields["model"] if "model" in fields else current.provider.model
    if model is None:
        model = current.provider.model

    api_key = current.provider.api_key
    if "api_key" in fields and fields["api_key"] not in (None, ""):
        api_key = fields["api_key"]

    if "base_url" in fields:
        base_url = fields["base_url"] or None
    else:
        base_url = current.provider.base_url

    if "provider_params" in fields and fields["provider_params"] is not None:
        provider_params = fields["provider_params"]
    else:
        provider_params = current.provider.provider_params

    if "workspace_path" in fields:
        raw_path = fields["workspace_path"]
        workspace_path = "" if raw_path is None else str(raw_path)
    else:
        workspace_path = current.workspace_path

    def pick(name: str, current_value: Any) -> Any:
        if name in fields and fields[name] is not None:
            return fields[name]
        return current_value

    return LoadedConfig(
        provider=ProviderConfig(
            model=str(model),
            api_key=api_key,
            base_url=base_url,
            provider_params=provider_params,
        ),
        policy=ExecutionPolicy(
            command_timeout_seconds=pick(
                "command_timeout_seconds", current.policy.command_timeout_seconds
            ),
            max_command_output_bytes=pick(
                "max_command_output_bytes", current.policy.max_command_output_bytes
            ),
            max_context_message_chars=pick(
                "max_context_message_chars", current.policy.max_context_message_chars
            ),
        ),
        workspace_path=workspace_path,
    )
