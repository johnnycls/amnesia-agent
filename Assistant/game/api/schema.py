"""Structured-output schema the Main screen sends with every turn."""

from __future__ import annotations

from typing import Any

# Stage fields for Assistant v1: message, choices, bg, expression, bgm.
ASSISTANT_STAGE: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "assistant_stage",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "choices": {"type": "array", "items": {"type": "string"}},
                "bg": {"type": "string"},
                "expression": {"type": "string"},
                "bgm": {"type": "string"},
            },
            "required": ["message", "choices", "bg", "expression", "bgm"],
            "additionalProperties": False,
        },
    },
}
