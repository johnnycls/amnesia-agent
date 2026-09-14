"""LLM message assembly and memory loading."""

from typing import Any, cast

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import ConfigError, ProviderError
from amnesia_agent_kernel.workspace import Workspace


def truncate_middle(text: str, max_chars: int) -> str:
    """Keep both ends of text within the limit, joined by a middle separator."""
    if not isinstance(text, str):
        raise ProviderError("Message content must be text")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise ConfigError("max_context_message_chars must be a positive integer")
    if len(text) <= max_chars:
        return text
    separator = "\n...\n"
    body = max_chars - len(separator)
    if body < 2:
        return separator[:max_chars]
    half = body // 2
    return f"{text[: body - half]}{separator}{text[-half:]}"


def build_messages(
    system_prompt: str,
    user_input: str,
    turn_messages: list[AllMessageValues],
    max_context_message_chars: int,
    workspace: Workspace,
) -> list[AllMessageValues]:
    """Assemble system, user, and same-turn messages."""
    if not isinstance(system_prompt, str) or not isinstance(user_input, str):
        raise ProviderError("Prompt and user input must be text")
    if not isinstance(turn_messages, list) or not all(
        isinstance(message, dict) for message in turn_messages
    ):
        raise ProviderError("Turn messages were malformed")
    if (
        isinstance(max_context_message_chars, bool)
        or not isinstance(max_context_message_chars, int)
        or max_context_message_chars <= 0
    ):
        raise ConfigError("max_context_message_chars must be a positive integer")
    memory = workspace.read_memory()
    if not isinstance(memory, str):
        raise ProviderError("Memory content must be text")
    messages: list[AllMessageValues] = []
    system_parts = [part for part in (system_prompt, memory) if part]
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    messages.append({"role": "user", "content": user_input})
    for message in turn_messages:
        content: Any = message.get("content")
        if (
            message.get("role") not in ("user", "system")
            and isinstance(content, str)
            and len(content) > max_context_message_chars
        ):
            truncated = cast(
                AllMessageValues,
                {
                    **message,
                    "content": truncate_middle(content, max_context_message_chars),
                },
            )
            messages.append(truncated)
        else:
            messages.append(message)
    return messages
