"""Minimal SSE parser for server event streams."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any


class SseError(RuntimeError):
    """Malformed SSE payload from the server."""


def parse_sse(lines: Iterator[Any]) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from ``data:`` lines; ignore comments and blanks."""
    for raw_line in lines:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8")
        else:
            line = str(raw_line)
        line = line.rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        try:
            value: Any = json.loads(line[5:].lstrip())
        except json.JSONDecodeError as error:
            raise SseError("Server returned malformed SSE JSON") from error
        if not isinstance(value, dict):
            raise SseError("Server SSE data must be a JSON object")
        yield value
