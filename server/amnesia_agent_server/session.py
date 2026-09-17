"""SessionManager: config-backed KernelSession construction and path-keyed turns."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from typing import Any

from amnesia_agent_kernel import (
    AgentError,
    ExecutionPolicy,
    KernelSession,
    ProviderConfig,
    WorkspaceError,
)
from amnesia_agent_kernel.workspace.paths import resolve_root
from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_server.config import (
    ConfigStore,
    LoadedConfig,
    public_config,
    reject_provider_params_secrets,
    resolve_request_workspace_path,
)
from amnesia_agent_server.constants import API_VERSION
from amnesia_agent_server.sse import event_envelope

logger = logging.getLogger(__name__)


class TurnBusyError(Exception):
    """Raised when an operation cannot run while a turn is active."""


def _error_event(error_type: str, message: str, request_id: str) -> dict[str, Any]:
    """Build one terminal SSE error envelope with a support reference."""
    return {
        "type": "error",
        "data": {
            "error_type": error_type,
            "message": message,
            "request_id": request_id,
        },
    }


def resolved_workspace_key(workspace_path: str | None) -> str:
    """Resolved realpath string used as the turn lock key.

    Matches kernel ``resolve_root`` (expanduser + ``resolve(strict=False)``) after
    request normalization: omit / ``None`` / empty → default ``~/.amnesia-agent``
    so those request forms share one lock. A symlink and its target share one key.
    """
    return str(resolve_root(resolve_request_workspace_path(workspace_path)))


class SessionManager:
    """Own config loading, fresh KernelSession construction, and path-keyed turns.

    Strategy A: do **not** cache ``KernelSession`` across turns. Every turn and
    every workspace read/update builds a new session from the latest config.
    Workspace root comes from the per-request ``workspace_path`` (not config).

    Concurrency: one active turn per resolved workspace path. Different paths
    may run turns in parallel. Config update/reset requires no active turns.
    """

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        instance_id: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self.config_store = config_store or ConfigStore()
        self.instance_id = instance_id
        self.workspace_root = workspace_root
        self.config_store.setup()
        # Path key → in-flight turn iterator (None until the kernel stream starts).
        self._active: dict[str, AsyncIterator[Any] | None] = {}

    @property
    def active_turn(self) -> bool:
        """True when any workspace currently has an active turn."""
        return bool(self._active)

    @property
    def active_workspaces(self) -> list[str]:
        """Resolved workspace path keys with an active turn (sorted)."""
        return sorted(self._active)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "active_turn": self.active_turn,
            "active_workspaces": self.active_workspaces,
            "api_version": API_VERSION,
            "instance_id": self.instance_id,
        }

    def _workspace_path(self, workspace_path: str | None) -> str | None:
        """Resolve and confine a request path when remote mode has a root."""
        if self.workspace_root is None:
            return resolve_request_workspace_path(workspace_path)
        root = resolve_root(self.workspace_root)
        requested_value = resolve_request_workspace_path(workspace_path) or self.workspace_root
        requested = resolve_root(requested_value)
        try:
            requested.relative_to(root)
        except ValueError as error:
            raise WorkspaceError(
                "Workspace path is outside the server workspace root",
                path=str(requested),
            ) from error
        return str(requested)

    def require_idle_for_path(self, workspace_path: str | None, action: str) -> None:
        """Raise if the resolved workspace path already has an active turn."""
        key = resolved_workspace_key(self._workspace_path(workspace_path))
        if key in self._active:
            raise TurnBusyError(f"Cannot {action} during an active turn")

    def require_no_active_turns(self, action: str) -> None:
        """Raise if any workspace has an active turn (config mutations)."""
        if self._active:
            raise TurnBusyError(f"Cannot {action} during an active turn")

    def _loaded(self) -> LoadedConfig:
        return self.config_store.load()

    def build_session(
        self,
        loaded: LoadedConfig | None = None,
        *,
        workspace_path: str | None = None,
    ) -> KernelSession:
        """Construct a fresh ``KernelSession`` from config + request workspace path."""
        config = loaded if loaded is not None else self._loaded()
        return KernelSession(
            config.provider,
            config.policy,
            workspace_root=self._workspace_path(workspace_path),
        )

    def read_config(self) -> dict[str, Any]:
        return public_config(self.config_store.load())

    def update_config(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Apply a partial config update; omit keys to keep current values."""
        self.require_no_active_turns("change configuration")
        current = self.config_store.load()
        updated = _merge_config(current, fields)
        self.config_store.save(updated)
        return public_config(updated)

    def reset_config(self) -> dict[str, Any]:
        self.require_no_active_turns("reset configuration")
        return public_config(self.config_store.reset())

    def check_workspace(self, workspace_path: str | None = None) -> bool:
        return KernelSession.check_workspace(self._workspace_path(workspace_path))

    def setup_or_repair_workspace(self, workspace_path: str | None = None) -> None:
        self.require_idle_for_path(workspace_path, "setup or repair workspace")
        KernelSession.setup_or_repair_workspace(self._workspace_path(workspace_path))

    def create_workspace(self, workspace_path: str | None = None) -> None:
        self.require_idle_for_path(workspace_path, "create workspace")
        KernelSession.create_workspace(self._workspace_path(workspace_path))

    def create_or_reset_workspace(self, workspace_path: str | None = None) -> None:
        self.require_idle_for_path(workspace_path, "create or reset workspace")
        KernelSession.create_or_reset_workspace(self._workspace_path(workspace_path))

    def read_system_prompt(self, workspace_path: str | None = None) -> str:
        return self.build_session(workspace_path=workspace_path).read_system_prompt()

    def update_system_prompt(self, content: str, workspace_path: str | None = None) -> str:
        self.require_idle_for_path(workspace_path, "update system prompt")
        self.build_session(workspace_path=workspace_path).update_system_prompt(content)
        return content

    def read_memory(self, workspace_path: str | None = None) -> str:
        return self.build_session(workspace_path=workspace_path).read_memory()

    def update_memory(self, content: str, workspace_path: str | None = None) -> str:
        self.require_idle_for_path(workspace_path, "update memory")
        self.build_session(workspace_path=workspace_path).update_memory(content)
        return content

    def list_history(self, workspace_path: str | None = None) -> list[str]:
        return self.build_session(workspace_path=workspace_path).list_history()

    def read_history(
        self,
        date: str | None = None,
        workspace_path: str | None = None,
    ) -> list[AllMessageValues]:
        return list(self.build_session(workspace_path=workspace_path).read_history(date))

    def update_history(
        self,
        messages: Sequence[AllMessageValues],
        date: str | None = None,
        workspace_path: str | None = None,
    ) -> None:
        self.require_idle_for_path(workspace_path, "update history")
        self.build_session(workspace_path=workspace_path).update_history(messages, date)

    def reset_history(self, workspace_path: str | None = None) -> None:
        self.require_idle_for_path(workspace_path, "reset history")
        self.build_session(workspace_path=workspace_path).reset_history()

    def start_turn(
        self,
        user_input: str,
        response_format: Mapping[str, Any] | None = None,
        workspace_path: str | None = None,
        system_prompt_prefix: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Acquire the path slot and return the SSE envelope stream.

        ``response_format`` is optional structured-output JSON passed through to
        ``KernelSession.turn`` (``None`` / omitted → no structured output).

        ``workspace_path`` is optional; omit/empty → kernel default workspace.

        Raises ``TurnBusyError`` synchronously so callers can map it to HTTP 409
        before starting a streaming response when that resolved path is busy.
        The caller must ``aclose`` the returned generator (e.g. via
        ``contextlib.aclosing``) so the path slot is released on disconnect or
        cancel.

        Different resolved workspace paths may run turns concurrently.
        """
        workspace_path = self._workspace_path(workspace_path)
        key = resolved_workspace_key(workspace_path)
        if key in self._active:
            raise TurnBusyError("Another turn is already active for this workspace")
        self._active[key] = None
        request_id = uuid.uuid4().hex[:12]
        return self._stream_turn(
            user_input,
            response_format,
            workspace_path,
            system_prompt_prefix,
            key,
            request_id,
        )

    async def _stream_turn(
        self,
        user_input: str,
        response_format: Mapping[str, Any] | None,
        workspace_path: str | None,
        system_prompt_prefix: str,
        key: str,
        request_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE envelopes for one turn; release the path slot in ``finally``."""
        try:
            try:
                session = self.build_session(workspace_path=workspace_path)
                turn_events = session.turn(
                    user_input,
                    response_format=response_format,
                    system_prompt_prefix=system_prompt_prefix,
                )
                self._active[key] = turn_events
                async with aclosing(turn_events):
                    async for event in turn_events:
                        yield event_envelope(event)
                    yield {"type": "done", "data": {}}
            except AgentError as error:
                yield _error_event(type(error).__name__, str(error), request_id)
            except ValueError:
                logger.exception("Turn %s failed with an unexpected value error", request_id)
                yield _error_event(
                    "InternalServerError",
                    "The turn failed unexpectedly.",
                    request_id,
                )
            except Exception:
                logger.exception("Turn %s failed unexpectedly", request_id)
                yield _error_event(
                    "InternalServerError",
                    "The turn failed unexpectedly.",
                    request_id,
                )
        finally:
            self._active.pop(key, None)

    async def cancel_active_turn(self) -> None:
        """Best-effort aclose of every in-flight kernel turn iterator."""
        for turn_events in list(self._active.values()):
            if turn_events is not None:
                aclose = getattr(turn_events, "aclose", None)
                if callable(aclose):
                    await aclose()


def _merge_config(current: LoadedConfig, fields: Mapping[str, Any]) -> LoadedConfig:
    model = fields["model"] if "model" in fields else current.provider.model
    if model is None:
        model = current.provider.model

    if "api_key" in fields:
        api_key = fields["api_key"] or None
    else:
        api_key = current.provider.api_key

    if "base_url" in fields:
        base_url = fields["base_url"] or None
    else:
        base_url = current.provider.base_url

    if "provider_params" in fields and fields["provider_params"] is not None:
        provider_params = fields["provider_params"]
        reject_provider_params_secrets(provider_params)
    else:
        provider_params = current.provider.provider_params

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
    )
