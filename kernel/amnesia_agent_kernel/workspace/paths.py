"""Workspace path constants and date helpers."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from amnesia_agent_kernel.errors import WorkspaceError

DEFAULT_WORKSPACE = Path.home() / ".amnesia-agent"
WORKSPACE_FILES: tuple[str, ...] = (
    "system_prompt.md",
    "memory.md",
)
HISTORY_DIRECTORY = "history"
HISTORY_FILENAME = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\.jsonl")


def resolve_root(root: str | os.PathLike[str] | None) -> Path:
    """Normalize a workspace root to a realpath for identity and lock keys.

    Uses ``expanduser`` then ``resolve(strict=False)`` so relative and absolute
    forms of the same path collide, and a symlink shares identity with its
    target. Missing path components are accepted (``strict=False``).
    """
    if root is not None and (isinstance(root, bool) or not isinstance(root, (str, os.PathLike))):
        raise WorkspaceError(f"Invalid workspace root {root!r}")
    if root == "":
        raise WorkspaceError("Workspace root must not be empty")
    try:
        path = Path(root).expanduser() if root is not None else DEFAULT_WORKSPACE
        return path.resolve(strict=False)
    except (OSError, TypeError, ValueError) as e:
        raise WorkspaceError(f"Invalid workspace root {root!r}: {e}") from e


def validate_date(value: str) -> str:
    if not isinstance(value, str):
        raise WorkspaceError("History date must be an ISO date in YYYY-MM-DD format")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise WorkspaceError(f"Invalid history date {value!r}; expected YYYY-MM-DD") from e
    if parsed.isoformat() != value:
        raise WorkspaceError(f"Invalid history date {value!r}; expected YYYY-MM-DD")
    return value


def history_path(root: Path, date: str) -> Path:
    return root / HISTORY_DIRECTORY / f"{date}.jsonl"


def utc_date_string(now: datetime) -> str:
    if not isinstance(now, datetime):
        raise TypeError("clock must return datetime")
    current = now if now.tzinfo is None else now.astimezone(timezone.utc)
    return current.date().isoformat()
