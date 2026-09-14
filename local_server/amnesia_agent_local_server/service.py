"""Deep application service behind the local HTTP routes."""

import json
from collections.abc import AsyncGenerator, Mapping
from typing import Any

from amnesia_agent_kernel import AgentError, KernelSession

from amnesia_agent_local_server.config import ConfigStore, LoadedConfig, public_config
from amnesia_agent_local_server.protocol import RESPONSE_FORMAT, ConfigUpdate


class TurnBusyError(Exception):
    """Raised when a second turn is requested while one is active."""


class AgentService:
    """Own config, one kernel session, and the local server's turn lifecycle."""

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
    def active(self) -> bool:
        return self._active

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "active_turn": self._active,
            "api_version": "v1",
            "instance_id": self.instance_id,
        }

    def read_config(self) -> dict[str, Any]:
        return public_config(self.config_store.load())

    def update_config(self, update: ConfigUpdate) -> dict[str, Any]:
        if self._active:
            raise TurnBusyError("Cannot change configuration during an active turn")
        current = self.config_store.load()
        raw_fields = getattr(update, "model_fields_set", None)
        if raw_fields is None:
            raw_fields = getattr(update, "__fields_set__", set())
        fields: set[str] = set(raw_fields or ())

        model = update.model if update.model is not None else current.provider.model
        api_key = current.provider.api_key
        if "api_key" in fields and update.api_key not in (None, ""):
            api_key = update.api_key
        base_url = current.provider.base_url
        if "base_url" in fields:
            base_url = update.base_url or None
        provider_params = (
            update.provider_params
            if update.provider_params is not None
            else current.provider.provider_params
        )
        provider = current.provider.__class__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            provider_params=provider_params,
        )
        policy = current.policy.__class__(
            command_timeout_seconds=(
                update.command_timeout_seconds
                if update.command_timeout_seconds is not None
                else current.policy.command_timeout_seconds
            ),
            max_command_output_bytes=(
                update.max_command_output_bytes
                if update.max_command_output_bytes is not None
                else current.policy.max_command_output_bytes
            ),
            max_context_message_chars=(
                update.max_context_message_chars
                if update.max_context_message_chars is not None
                else current.policy.max_context_message_chars
            ),
        )
        updated = LoadedConfig(provider=provider, policy=policy)
        self.config_store.save(updated)
        self._session = None
        return public_config(updated)

    def reset_config(self) -> dict[str, Any]:
        if self._active:
            raise TurnBusyError("Cannot reset configuration during an active turn")
        self._session = None
        return public_config(self.config_store.reset())

    def _get_session(self) -> KernelSession:
        if self._session is None:
            loaded = self.config_store.load()
            self._session = KernelSession(loaded.provider, loaded.policy)
        return self._session

    def _reserve_turn(self) -> KernelSession:
        if self._active:
            raise TurnBusyError("Another turn is already active")
        session = self._get_session()
        self._active = True
        return session

    def _require_idle(self, action: str) -> None:
        if self._active:
            raise TurnBusyError(f"Cannot {action} during an active turn")

    async def stream_turn(self, user_input: str) -> AsyncGenerator[dict[str, Any], None]:
        """Yield typed event payloads and release the active-turn slot reliably."""
        session = self._reserve_turn()
        try:
            async for event in session.turn(user_input, response_format=RESPONSE_FORMAT):
                yield event_payload(event)
            yield {"type": "done", "data": {}}
        except TurnBusyError as error:
            yield {"type": "error", "data": {"error_type": "TurnBusyError", "message": str(error)}}
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

    def check_workspace(self) -> bool:
        return KernelSession.check_workspace()

    def setup_or_repair_workspace(self) -> None:
        self._require_idle("setup or repair workspace")
        KernelSession.setup_or_repair_workspace()
        self._session = None

    def create_or_reset_workspace(self) -> None:
        self._require_idle("create or reset workspace")
        KernelSession.create_or_reset_workspace()
        self._session = None

    def read_system_prompt(self) -> str:
        return self._get_session().read_system_prompt()

    def update_system_prompt(self, content: str) -> str:
        self._get_session().update_system_prompt(content)
        return content

    def read_memory(self) -> str:
        return self._get_session().read_memory()

    def update_memory(self, content: str) -> str:
        self._get_session().update_memory(content)
        return content

    def list_history(self) -> list[str]:
        return self._get_session().list_history()

    def read_history(self, date: str | None = None) -> list[Any]:
        return list(self._get_session().read_history(date))

    def reset_history(self) -> None:
        self._require_idle("reset history")
        self._get_session().reset_history()


def _message_data(message: Mapping[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list):
        calls = []
    data: dict[str, Any] = {"content": content, "tool_calls": calls}
    if not calls:
        structured = _parse_structured_answer(content)
        if structured is None:
            data.update({"structured": False, "answer": content, "choices": []})
        else:
            data.update({"structured": True, **structured})
    return data


def _parse_structured_answer(content: str) -> dict[str, Any] | None:
    try:
        raw: Any = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    answer = raw.get("answer")
    choices = raw.get("choices")
    if not isinstance(answer, str) or not isinstance(choices, list):
        return None
    if not all(isinstance(choice, str) for choice in choices):
        return None
    return {"answer": answer, "choices": choices}


def _tool_data(message: Mapping[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    return {"content": content if isinstance(content, str) else str(content)}


def event_payload(event: Any) -> dict[str, Any]:
    """Convert a kernel turn event into the stable wire envelope.

    Kernel ``turn`` yields ``str`` deltas and ``AllMessageValues`` role messages.
    Unexpected shapes raise ``ValueError``.
    """
    if isinstance(event, str):
        return {"type": "delta", "data": {"text": event}}
    if isinstance(event, Mapping):
        role = event.get("role")
        if role == "assistant":
            data = _message_data(event)
            if data.get("tool_calls"):
                return {"type": "tool_call", "data": data}
            return {"type": "assistant", "data": data}
        if role == "tool":
            return {"type": "tool_result", "data": _tool_data(event)}
    raise ValueError(f"Unexpected kernel event type: {type(event).__name__!r}")
