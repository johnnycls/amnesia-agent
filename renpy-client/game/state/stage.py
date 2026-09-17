"""Apply assistant_stage structured fields to UI stage state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StageApplyResult:
    """Outcome of applying one assistant stage payload."""

    message: str
    choices: list[str]
    bg: str | None
    expression: str | None
    bgm: str | None
    warnings: list[str]


def apply_stage(
    data: dict[str, Any],
    *,
    background_ids: set[str],
    expression_ids: set[str],
    bgm_ids: set[str],
    previous_bg: str,
    previous_expression: str,
    previous_bgm: str,
) -> StageApplyResult:
    """Extract stage fields; keep previous assets when ids are invalid."""
    warnings: list[str] = []

    raw_message = data.get("message", data.get("content", ""))
    message = raw_message if isinstance(raw_message, str) else str(raw_message)

    raw_choices = data.get("choices") or []
    if isinstance(raw_choices, list):
        choices = [c for c in raw_choices if isinstance(c, str)]
    else:
        choices = []
        warnings.append("choices was not an array; ignored")

    bg = previous_bg
    raw_bg = data.get("bg")
    if isinstance(raw_bg, str) and raw_bg in background_ids:
        bg = raw_bg
    elif raw_bg is not None:
        warnings.append(f"Unknown bg id {raw_bg!r}; kept {previous_bg!r}")

    expression = previous_expression
    raw_expr = data.get("expression")
    if isinstance(raw_expr, str) and raw_expr in expression_ids:
        expression = raw_expr
    elif raw_expr is not None:
        warnings.append(
            f"Unknown expression id {raw_expr!r}; kept {previous_expression!r}"
        )

    bgm = previous_bgm
    raw_bgm = data.get("bgm")
    if isinstance(raw_bgm, str) and raw_bgm in bgm_ids:
        bgm = raw_bgm
    elif raw_bgm is None:
        warnings.append(f"Missing bgm; kept {previous_bgm!r}")
    else:
        warnings.append(f"Unknown bgm id {raw_bgm!r}; kept {previous_bgm!r}")

    return StageApplyResult(
        message=message,
        choices=choices,
        bg=bg,
        expression=expression,
        bgm=bgm,
        warnings=warnings,
    )
