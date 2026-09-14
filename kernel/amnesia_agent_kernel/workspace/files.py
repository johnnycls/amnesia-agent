"""Workspace text-file read and update helpers."""

from pathlib import Path

from amnesia_agent_kernel.errors import WorkspaceError
from amnesia_agent_kernel.workspace.paths import WORKSPACE_FILES


def read_text(root: Path, filename: str) -> str:
    path = root / filename
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as e:
        raise WorkspaceError(f"Cannot read file {path}: {e}", path=str(path)) from e


def write_text(root: Path, filename: str, content: str) -> None:
    path = root / filename
    try:
        path.write_text(content, encoding="utf-8")
    except (OSError, UnicodeError, TypeError) as e:
        raise WorkspaceError(f"Cannot write file {path}: {e}", path=str(path)) from e


def setup_workspace_files(root: Path) -> None:
    """Create the workspace directory and empty prompt/memory files when missing."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        for filename in WORKSPACE_FILES:
            path = root / filename
            if not path.exists():
                path.write_text("", encoding="utf-8")
    except (OSError, TypeError, ValueError) as e:
        raise WorkspaceError(
            f"Cannot initialize workspace {root}: {e}", path=str(root)
        ) from e
