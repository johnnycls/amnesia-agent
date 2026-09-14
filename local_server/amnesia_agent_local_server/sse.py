"""Map kernel turn events to SSE wire envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from litellm.types.llms.openai import AllMessageValues


def encode_sse(payload: dict[str, Any]) -> str:
    """Serialize one SSE ``data:`` frame."""
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def event_envelope(event: str | AllMessageValues) -> dict[str, Any]:
    """Convert a kernel ``turn`` yield into a typed wire envelope.

    Kernel ``turn`` yields ``str`` deltas and ``AllMessageValues`` role messages.
    Unexpected shapes raise ``ValueError`` (fail loud).
    """
    if isinstance(event, str):
        return {"type": "delta", "data": {"text": event}}
    if isinstance(event, Mapping):
        role = event.get("role")
        if role == "assistant":
            data = _assistant_data(event)
            if data.get("tool_calls"):
                return {"type": "tool_call", "data": data}
            return {"type": "assistant", "data": data}
        if role == "tool":
            return {"type": "tool_result", "data": _tool_data(event)}
    raise ValueError(f"Unexpected kernel event type: {type(event).__name__!r}")


def _assistant_data(message: Mapping[str, Any]) -> dict[str, Any]:
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
