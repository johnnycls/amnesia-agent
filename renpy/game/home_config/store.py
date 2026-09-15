"""Persist Ren'Py frontend settings at ~/.amnesia-agent-renpy/config.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

DEFAULT_CONFIG_DIR = Path.home() / ".amnesia-agent-renpy"
DEFAULT_LANGUAGE: Final[str] = "english"
SUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset(
    {"english", "schinese", "tchinese", "japanese", "korean"}
)
_CONFIG_KEYS = frozenset({"language", "recent_workspaces"})


class ConfigError(RuntimeError):
    """Corrupt or invalid Ren'Py config (fail loud; no silent repair)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class WorkspaceEntry:
    path: str
    last_opened_at: str


@dataclass(frozen=True)
class RenpyConfig:
    language: str
    recent_workspaces: tuple[WorkspaceEntry, ...]


def default_config_dict() -> dict[str, Any]:
    return {"language": DEFAULT_LANGUAGE, "recent_workspaces": []}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RenpyConfigStore:
    """Load / save / reset Ren'Py home JSON. Missing → lazy defaults; corrupt → raise."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        if root is None:
            self.root = DEFAULT_CONFIG_DIR.resolve(strict=False)
        else:
            self.root = Path(root).expanduser().resolve(strict=False)

    @property
    def path(self) -> Path:
        return self.root / "config.json"

    def load(self) -> RenpyConfig:
        if not self.path.exists():
            self.write_defaults()
        try:
            with self.path.open(encoding="utf-8-sig") as file:
                raw: Any = json.load(file)
        except OSError as error:
            raise ConfigError(
                f"Cannot read Ren'Py config {self.path}: {error}", path=str(self.path)
            ) from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ConfigError(
                f"Malformed Ren'Py config JSON in {self.path}: {error}",
                path=str(self.path),
            ) from error
        return self._parse(raw)

    def save(self, config: RenpyConfig) -> None:
        self._atomic_write(self._to_raw(config))

    def reset(self) -> RenpyConfig:
        self.write_defaults()
        return self.load()

    def write_defaults(self) -> None:
        self._atomic_write(default_config_dict())

    def bump_recent(self, workspace_path: str) -> RenpyConfig:
        """Move/insert workspace at top of recent list and persist."""
        config = self.load()
        normalized = str(Path(workspace_path).expanduser().resolve(strict=False))
        now = utc_now_iso()
        entries = [
            WorkspaceEntry(path=e.path, last_opened_at=e.last_opened_at)
            for e in config.recent_workspaces
            if e.path != normalized
        ]
        entries.insert(0, WorkspaceEntry(path=normalized, last_opened_at=now))
        updated = RenpyConfig(
            language=config.language, recent_workspaces=tuple(entries)
        )
        self.save(updated)
        return updated

    def remove_recent(self, workspace_path: str) -> RenpyConfig:
        config = self.load()
        normalized = str(Path(workspace_path).expanduser().resolve(strict=False))
        entries = tuple(e for e in config.recent_workspaces if e.path != normalized)
        updated = RenpyConfig(language=config.language, recent_workspaces=entries)
        self.save(updated)
        return updated

    def set_language(self, language: str) -> RenpyConfig:
        if language not in SUPPORTED_LANGUAGES:
            raise ConfigError(f"Unsupported language: {language!r}")
        config = self.load()
        updated = RenpyConfig(
            language=language, recent_workspaces=config.recent_workspaces
        )
        self.save(updated)
        return updated

    def _atomic_write(self, raw: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            os.chmod(self.path, 0o600)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ConfigError(
                f"Cannot write Ren'Py config {self.path}: {error}",
                path=str(self.path),
            ) from error

    def _parse(self, raw: Any) -> RenpyConfig:
        if not isinstance(raw, dict):
            raise ConfigError(
                "Ren'Py config.json must contain a JSON object.", path=str(self.path)
            )
        unknown = set(raw) - _CONFIG_KEYS
        if unknown:
            name = next(iter(unknown))
            raise ConfigError(
                f"Invalid Ren'Py config at {name}: unexpected property",
                path=str(self.path),
            )
        language = raw.get("language", DEFAULT_LANGUAGE)
        if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
            raise ConfigError(
                f"Invalid Ren'Py config language: {language!r}", path=str(self.path)
            )
        recent_raw = raw.get("recent_workspaces", [])
        if not isinstance(recent_raw, list):
            raise ConfigError(
                "recent_workspaces must be a JSON array.", path=str(self.path)
            )
        entries: list[WorkspaceEntry] = []
        for index, item in enumerate(recent_raw):
            if not isinstance(item, dict):
                raise ConfigError(
                    f"recent_workspaces[{index}] must be an object.",
                    path=str(self.path),
                )
            path = item.get("path")
            opened = item.get("last_opened_at")
            if not isinstance(path, str) or not path.strip():
                raise ConfigError(
                    f"recent_workspaces[{index}].path must be a non-empty string.",
                    path=str(self.path),
                )
            if not isinstance(opened, str) or not opened.strip():
                raise ConfigError(
                    f"recent_workspaces[{index}].last_opened_at must be a string.",
                    path=str(self.path),
                )
            extra = set(item) - {"path", "last_opened_at"}
            if extra:
                raise ConfigError(
                    f"recent_workspaces[{index}] unexpected property "
                    f"{next(iter(extra))}",
                    path=str(self.path),
                )
            entries.append(WorkspaceEntry(path=path, last_opened_at=opened))
        entries.sort(key=lambda e: e.last_opened_at, reverse=True)
        return RenpyConfig(language=language, recent_workspaces=tuple(entries))

    @staticmethod
    def _to_raw(config: RenpyConfig) -> dict[str, Any]:
        sorted_entries = sorted(
            config.recent_workspaces, key=lambda e: e.last_opened_at, reverse=True
        )
        return {
            "language": config.language,
            "recent_workspaces": [
                {"path": e.path, "last_opened_at": e.last_opened_at}
                for e in sorted_entries
            ],
        }
