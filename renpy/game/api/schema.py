"""Structured-output schema the Main screen sends with every turn."""

from __future__ import annotations

from typing import Any

# Matches local_server README "answer_with_choices" example.
ANSWER_WITH_CHOICES: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer_with_choices",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "choices": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "choices"],
            "additionalProperties": False,
        },
    },
}
