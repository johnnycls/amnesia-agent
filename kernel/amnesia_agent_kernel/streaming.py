"""Streaming helpers for assembling assistant messages from provider deltas."""

from typing import Any

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import ProviderError


def _stream_delta(chunk: Any) -> Any:
    choices = getattr(chunk, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise ProviderError("LLM stream returned no choices")
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        raise ProviderError("LLM stream returned no delta")
    return delta


def _assistant_message(parts: list[str], calls: dict[int, dict[str, Any]]) -> AllMessageValues:
    """Build the assistant message from streamed content and tool-call slots."""
    message: dict[str, Any] = {"role": "assistant", "content": "".join(parts)}
    tool_calls: list[dict[str, Any]] = []
    for index, slot in sorted(calls.items()):
        if not isinstance(index, int) or index < 0 or not isinstance(slot, dict):
            raise ProviderError("Malformed streamed tool call index")
        function = slot.get("function")
        if not isinstance(function, dict):
            raise ProviderError("Malformed streamed tool call function")
        name = function.get("name", "")
        arguments = function.get("arguments", "")
        call_id = slot.get("id", "")
        if not all(isinstance(value, str) for value in (call_id, name, arguments)):
            raise ProviderError("Malformed streamed tool call fields")
        if not call_id:
            raise ProviderError("Streamed tool call had no ID")
        if not name:
            raise ProviderError("Streamed tool call had no function name")
        tool_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        )
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message
