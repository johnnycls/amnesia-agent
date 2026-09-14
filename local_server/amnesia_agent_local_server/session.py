"""One KernelSession lifecycle: rebuild from config, turn busy lock, invalidate."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any

from amnesia_agent_kernel import AgentError, ExecutionPolicy, KernelSession, ProviderConfig
from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_local_server.config import ConfigStore, LoadedConfig, public_config
from amnesia_agent_local_server.sse import event_envelope

# Structured output requested for desktop frontends (answer + choice chips).
RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer_with_choices",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "choices": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "choices"],
            "additionalProperties": False,
        },
    },
}


class TurnBusyError(Exception):
    """Raised when an operation cannot run while a turn is active."""


class SessionManager:
    """Own config-backed ``KernelSession`` rebuild and the turn busy lock."""

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        instance_id: str | None = None,
    ) -> None:
        self.config_store = config_store or ConfigStore()
        self.instance_id = instance_id
        self.config_store.setup()
        self._session: KernelSession | None = None
        self._active = False

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

    def invalidate(self) -> None:
        """Drop the cached session so the next use rebuilds from config."""
        self._session = None

    def require_idle(self, action: str) -> None:
        if self._active:
            raise TurnBusyError(f"Cannot {action} during an active turn")

    def get_session(self) -> KernelSession:
        if self._session is None:
            loaded = self.config_store.load()
            self._session = KernelSession(loaded.provider, loaded.policy)
        return self._session

    def read_config(self) -> dict[str, Any]:
        return public_config(self.config_store.load())

    def update_config(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a partial config update; omit keys to keep current values."""
        self.require_idle("change configuration")
        current = self.config_store.load()
        updated = _merge_config(current, fields)
        self.config_store.save(updated)
        self.invalidate()
        return public_config(updated)

    def reset_config(self) -> dict[str, Any]:
        self.require_idle("reset configuration")
        self.invalidate()
        return public_config(self.config_store.reset())

    def check_workspace(self) -> bool:
        return KernelSession.check_workspace()

    def setup_or_repair_workspace(self) -> None:
        self.require_idle("setup or repair workspace")
        KernelSession.setup_or_repair_workspace()
        self.invalidate()

    def create_or_reset_workspace(self) -> None:
        self.require_idle("create or reset workspace")
        KernelSession.create_or_reset_workspace()
        self.invalidate()

    def read_system_prompt(self) -> str:
        return self.get_session().read_system_prompt()

    def update_system_prompt(self, content: str) -> str:
        self.get_session().update_system_prompt(content)
        return content

    def read_memory(self) -> str:
        return self.get_session().read_memory()

    def update_memory(self, content: str) -> str:
        self.get_session().update_memory(content)
        return content

    def list_history(self) -> list[str]:
        return self.get_session().list_history()

    def read_history(self, date: str | None = None) -> list[AllMessageValues]:
        return list(self.get_session().read_history(date))

    def update_history(
        self,
        messages: Sequence[AllMessageValues],
        date: str | None = None,
    ) -> None:
        self.get_session().update_history(messages, date)

    def reset_history(self) -> None:
        self.require_idle("reset history")
        self.get_session().reset_history()

    async def stream_turn(self, user_input: str) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE envelopes for one turn; release the busy slot in ``finally``."""
        if self._active:
            raise TurnBusyError("Another turn is already active")
        session = self.get_session()
        self._active = True
        try:
            async for event in session.turn(user_input, response_format=RESPONSE_FORMAT):
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
            self._active = False


def _merge_config(current: LoadedConfig, fields: Mapping[str, Any]) -> LoadedConfig:
    model = fields["model"] if "model" in fields else current.provider.model
    if model is None:
        model = current.provider.model
    api_key = current.provider.api_key
    if "api_key" in fields and fields["api_key"] not in (None, ""):
        api_key = fields["api_key"]
    base_url = current.provider.base_url
    if "base_url" in fields:
        value = fields["base_url"]
        base_url = value or None
    provider_params = (
        fields["provider_params"]
        if "provider_params" in fields and fields["provider_params"] is not None
        else current.provider.provider_params
    )
    provider = ProviderConfig(
        model=str(model),
        api_key=api_key,
        base_url=base_url,
        provider_params=provider_params,
    )
    policy = ExecutionPolicy(
        command_timeout_seconds=(
            fields["command_timeout_seconds"]
            if "command_timeout_seconds" in fields
            and fields["command_timeout_seconds"] is not None
            else current.policy.command_timeout_seconds
        ),
        max_command_output_bytes=(
            fields["max_command_output_bytes"]
            if "max_command_output_bytes" in fields
            and fields["max_command_output_bytes"] is not None
            else current.policy.max_command_output_bytes
        ),
        max_context_message_chars=(
            fields["max_context_message_chars"]
            if "max_context_message_chars" in fields
            and fields["max_context_message_chars"] is not None
            else current.policy.max_context_message_chars
        ),
    )
    return LoadedConfig(provider=provider, policy=policy)
