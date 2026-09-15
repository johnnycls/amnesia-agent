"""Turn orchestration for the kernel."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import aclosing
from typing import Any, cast

from litellm import acompletion
from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import (
    ConfigError,
    ProviderError,
    ToolError,
    WorkspaceError,
)
from amnesia_agent_kernel.message import build_messages
from amnesia_agent_kernel.provider import (
    provider_error,
    request_kwargs,
    snapshot_response_format,
)
from amnesia_agent_kernel.streaming import assistant_message, stream_delta
from amnesia_agent_kernel.tools import SHELL_TOOL, execute_tool_calls
from amnesia_agent_kernel.types import ExecutionPolicy, ProviderConfig
from amnesia_agent_kernel.workspace import Workspace

logger = logging.getLogger(__name__)


def _record_user_failure(workspace: Workspace, text: str) -> None:
    workspace.append_history({"role": "user", "content": text})


def _persist_provider_failure(
    workspace: Workspace,
    error: ProviderError,
    parts: list[str] | None = None,
) -> None:
    if parts:
        workspace.append_history({"role": "assistant", "content": "".join(parts)})
    _record_user_failure(
        workspace,
        f"error: {type(error).__name__}: {error}",
    )


def _persist_interrupt(
    workspace: Workspace,
    parts: list[str],
    message_persisted: bool,
) -> None:
    if parts and not message_persisted:
        workspace.append_history({"role": "assistant", "content": "".join(parts)})
    _record_user_failure(workspace, "user interrupted")


async def agent_turn(
    config: ProviderConfig,
    policy: ExecutionPolicy,
    workspace: Workspace,
    user_input: str,
    response_format: Mapping[str, Any] | None = None,
) -> AsyncGenerator[str | AllMessageValues, None]:
    """Run one user turn until the model stops calling tools.

    Yields streamed text deltas as ``str``, then complete assistant or tool
    messages as ``AllMessageValues`` (distinguish via ``role``).

    Cancel / ``aclose`` behavior is phase-dependent (honesty over optimism):

    * **Pre-stream** (awaiting ``acompletion``): cancellation raises into the
      await; an interrupt marker is persisted when possible. There is no local
      stream to close yet; the in-flight HTTP request to the provider may still
      complete or bill upstream.
    * **Streaming** (iterating the LiteLLM response): ``aclose`` /
      ``aclosing`` closes the active ``CustomStreamWrapper`` when present,
      stops local consumption, and asks the HTTP client to release the
      connection. Upstream providers may still finish generating or bill
      tokens — best-effort, not a hard abort guarantee.
    * **Tools** (``execute_tool_calls`` / shell): cancellation cancels tool
      tasks and terminates the shell process group (SIGKILL / ``taskkill``).
      That local process kill is guaranteed when cleanup runs; any provider
      billing from earlier phases is unaffected.

    In all phases, partial assistant text (when present) and a user message
    ``user interrupted`` are persisted best-effort, then the cancel is
    re-raised.
    """
    if not isinstance(user_input, str):
        raise ConfigError("user_input must be text")
    response_format = snapshot_response_format(response_format)
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
                turn_kwargs: dict[str, Any] = {
                    "messages": messages,
                    "tools": [SHELL_TOOL],
                    "stream": True,
                }
                if response_format is not None:
                    turn_kwargs["response_format"] = response_format
                response: Any = await acompletion(**request_kwargs(config, **turn_kwargs))
            except Exception as e:
                error = provider_error(e, config)
                try:
                    _persist_provider_failure(workspace, error)
                except WorkspaceError as history_error:
                    raise history_error from error
                raise error from e

            calls: dict[int, dict[str, Any]] = {}
            try:
                async with aclosing(response):
                    async for chunk in response:
                        delta = stream_delta(chunk)
                        content = getattr(delta, "content", None)
                        if content is not None and not isinstance(content, str):
                            raise ProviderError("LLM stream content was not text")
                        if content:
                            parts.append(content)
                            yield content
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
                    message = assistant_message(parts, calls)
            except Exception as e:
                error = provider_error(e, config)
                try:
                    _persist_provider_failure(workspace, error, parts)
                except WorkspaceError as history_error:
                    raise history_error from error
                raise error from e

            workspace.append_history(message)
            message_persisted = True
            yield message
            tool_calls = cast(Sequence[dict[str, Any]], message.get("tool_calls", []))
            if not tool_calls:
                return
            turn_messages.append(message)
            try:
                tool_messages = await execute_tool_calls(
                    tool_calls,
                    timeout_seconds=policy.command_timeout_seconds,
                    max_output_bytes=policy.max_command_output_bytes,
                    cwd=workspace.root,
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
                yield tool_message
            turn_messages.extend(tool_messages)
    except (asyncio.CancelledError, GeneratorExit):
        try:
            _persist_interrupt(workspace, parts, message_persisted)
        except WorkspaceError:
            logger.error("Could not persist turn cancellation", exc_info=True)
        raise
