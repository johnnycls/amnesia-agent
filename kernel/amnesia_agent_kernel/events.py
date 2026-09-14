"""Events emitted by the kernel during an agent turn."""

from dataclasses import dataclass

from litellm.types.llms.openai import AllMessageValues


@dataclass(frozen=True)
class Delta:
    """A streamed fragment of assistant text."""

    text: str


@dataclass(frozen=True)
class AssistantMessage:
    """One complete model response, including text and any tool calls."""

    message: AllMessageValues


@dataclass(frozen=True)
class ToolResult:
    """The result message of one executed tool call."""

    message: AllMessageValues


Event = Delta | AssistantMessage | ToolResult
