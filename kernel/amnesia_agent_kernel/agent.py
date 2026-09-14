"""Turn orchestration for the kernel."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

from litellm import acompletion
from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import (
    ConfigError,
    ProviderError,
    ToolError,
    WorkspaceError,
)
from amnesia_agent_kernel.events import AssistantMessage, Delta, Event, ToolResult
from amnesia_agent_kernel.message import build_messages
from amnesia_agent_kernel.provider import (
    _provider_error,
    _request_kwargs,
    _snapshot_response_format,
)
from amnesia_agent_kernel.streaming import _assistant_message, _stream_delta
from amnesia_agent_kernel.tools import BASH_TOOL, execute_tool_calls
from amnesia_agent_kernel.types import ExecutionPolicy, ProviderConfig
from amnesia_agent_kernel.workspace import Workspace

logger = logging.getLogger(__name__)


def _record_user_failure(workspace: Workspace, text: str) -> None:
    workspace.append_history({"role": "user", "content": text})


def _persist_provider_failure(
    workspace: Workspace,
    provider_error: ProviderError,
    parts: list[str] | None = None,
) -> None:
    if parts:
        workspace.append_history({"role": "assistant", "content": "".join(parts)})
    _record_user_failure(
        workspace,
        f"error: {type(provider_error).__name__}: {provider_error}",
    )


async def agent_turn(
    config: ProviderConfig,
    policy: ExecutionPolicy,
    workspace: Workspace,
    user_input: str,
    response_format: Mapping[str, Any] | None = None,
) -> AsyncIterator[Event]:
    """Run one user turn until the model stops calling tools."""
    if not isinstance(user_input, str):
        raise ConfigError("user_input must be text")
    response_format = _snapshot_response_format(response_format)
    workspace.append_history({"role": "user", "content": user_input})
    turn_messages: list[AllMessageValues] = []
    parts: list[str] = []
    message_persisted = False
    try:
        while True:
            parts = []
            message_persisted = False
            messages: list[AllMessageValues] = build_messages(
                workspace.read_system_prompt(),
                user_input,
                turn_messages,
                policy.max_context_message_chars,
                workspace,
            )
            try:
                request_kwargs: dict[str, Any] = {
                    "messages": messages,
                    "tools": [BASH_TOOL],
                    "stream": True,
                }
                if response_format is not None:
                    request_kwargs["response_format"] = response_format
                response: Any = await acompletion(
                    **_request_kwargs(config, **request_kwargs)
                )
            except Exception as e:
                provider_error = _provider_error(e, config)
                try:
                    _persist_provider_failure(workspace, provider_error)
                except WorkspaceError as history_error:
                    raise history_error from provider_error
                raise provider_error from e

            calls: dict[int, dict[str, Any]] = {}
            try:
                async for chunk in response:
                    delta = _stream_delta(chunk)
                    content = getattr(delta, "content", None)
                    if content is not None and not isinstance(content, str):
                        raise ProviderError("LLM stream content was not text")
                    if content:
                        parts.append(content)
                        yield Delta(content)
                    raw_calls = getattr(delta, "tool_calls", None)
                    if raw_calls is not None and not isinstance(raw_calls, list):
                        raise ProviderError("LLM stream tool calls were malformed")
                    for call in raw_calls or []:
                        index = getattr(call, "index", None)
                        if index is None:
                            index = 0
                        if not isinstance(index, int) or index < 0:
                            raise ProviderError("LLM stream tool call index was invalid")
                        slot = calls.setdefault(
                            index, {"id": "", "function": {"name": "", "arguments": ""}}
                        )
                        call_id = getattr(call, "id", None)
                        if call_id is not None and not isinstance(call_id, str):
                            raise ProviderError("LLM stream tool call ID was invalid")
                        if call_id:
                            slot["id"] = call_id
                        function = getattr(call, "function", None)
                        if function is None:
                            continue
                        name = getattr(function, "name", None)
                        arguments = getattr(function, "arguments", None)
                        if name is not None and not isinstance(name, str):
                            raise ProviderError("LLM stream tool name was invalid")
                        if arguments is not None and not isinstance(arguments, str):
                            raise ProviderError("LLM stream tool arguments were invalid")
                        if name:
                            slot["function"]["name"] = name
                        if arguments:
                            slot["function"]["arguments"] += arguments
                message = _assistant_message(parts, calls)
            except Exception as e:
                provider_error = _provider_error(e, config)
                try:
                    _persist_provider_failure(workspace, provider_error, parts)
                except WorkspaceError as history_error:
                    raise history_error from provider_error
                raise provider_error from e

            workspace.append_history(message)
            message_persisted = True
            yield AssistantMessage(message)
            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
                return
            turn_messages.append(message)
            try:
                tool_messages = await execute_tool_calls(
                    tool_calls,
                    timeout_seconds=policy.command_timeout_seconds,
                    max_output_bytes=policy.max_command_output_bytes,
                )
            except ToolError as tool_error:
                try:
                    _record_user_failure(
                        workspace,
                        f"error: {type(tool_error).__name__}: {tool_error}",
                    )
                except WorkspaceError as history_error:
                    raise history_error from tool_error
                raise
            for tool_message in tool_messages:
                workspace.append_history(tool_message)
                yield ToolResult(tool_message)
            turn_messages.extend(tool_messages)
    except asyncio.CancelledError:
        try:
            if parts and not message_persisted:
                workspace.append_history({"role": "assistant", "content": "".join(parts)})
            _record_user_failure(workspace, "user interrupted")
        except WorkspaceError:
            logger.error("Could not persist turn cancellation", exc_info=True)
        raise
