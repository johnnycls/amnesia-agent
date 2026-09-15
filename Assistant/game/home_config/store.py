"""Persist Assistant frontend settings at ~/.amnesia-agent-assistant/config.json."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

DEFAULT_CONFIG_DIR = Path.home() / ".amnesia-agent-assistant"
DEFAULT_LANGUAGE: Final[str] = "english"
SUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset(
    {"english", "schinese", "tchinese", "japanese", "korean"}
)
_CONFIG_KEYS: Final[frozenset[str]] = frozenset({"selected_character_id", "language"})


class ConfigError(RuntimeError):
    """Corrupt or invalid Assistant config (fail loud; no silent repair)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class AssistantConfig:
    selected_character_id: str
    language: str = DEFAULT_LANGUAGE


def default_config_dict() -> dict[str, Any]:
    return {"selected_character_id": "", "language": DEFAULT_LANGUAGE}


class AssistantConfigStore:
    """Load / save / reset Assistant home JSON. Missing → lazy defaults; corrupt → raise."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        if root is None:
            self.root = DEFAULT_CONFIG_DIR.resolve(strict=False)
        else:
            self.root = Path(root).expanduser().resolve(strict=False)

    @property
    def path(self) -> Path:
        return self.root / "config.json"

    def load(self) -> AssistantConfig:
        if not self.path.exists():
            self.write_defaults()
        try:
            with self.path.open(encoding="utf-8-sig") as file:
                raw: Any = json.load(file)
        except OSError as error:
            raise ConfigError(
                f"Cannot read Assistant config {self.path}: {error}",
                path=str(self.path),
            ) from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ConfigError(
                f"Malformed Assistant config JSON in {self.path}: {error}",
                path=str(self.path),
            ) from error
        return self._parse(raw)

    def save(self, config: AssistantConfig) -> None:
        self._atomic_write(self._to_raw(config))

    def reset(self) -> AssistantConfig:
        self.write_defaults()
        return self.load()

    def write_defaults(self) -> None:
        self._atomic_write(default_config_dict())

    def set_selected_character(self, character_id: str) -> AssistantConfig:
        if not isinstance(character_id, str):
            raise ConfigError(
                f"selected_character_id must be a string, got {type(character_id).__name__}"
            )
        config = self.load()
        updated = AssistantConfig(
            selected_character_id=character_id.strip(),
            language=config.language,
        )
        self.save(updated)
        return updated

    def set_language(self, language: str) -> AssistantConfig:
        if language not in SUPPORTED_LANGUAGES:
            raise ConfigError(f"Unsupported language: {language!r}")
        config = self.load()
        updated = AssistantConfig(
            selected_character_id=config.selected_character_id,
            language=language,
        )
        self.save(updated)
        return updated

    def _atomic_write(self, raw: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            if os.name == "nt":
                # NTFS ignores full POSIX modes; best-effort clear read-only only.
                os.chmod(self.path, stat.S_IREAD | stat.S_IWRITE)
            else:
                os.chmod(self.path, 0o600)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ConfigError(
                f"Cannot write Assistant config {self.path}: {error}",
                path=str(self.path),
            ) from error

    def _parse(self, raw: Any) -> AssistantConfig:
        if not isinstance(raw, dict):
            raise ConfigError(
                "Assistant config.json must contain a JSON object.",
                path=str(self.path),
            )
        unknown = set(raw) - _CONFIG_KEYS
        if unknown:
            name = next(iter(unknown))
            raise ConfigError(
                f"Invalid Assistant config at {name}: unexpected property",
                path=str(self.path),
            )
        selected = raw.get("selected_character_id", "")
        if not isinstance(selected, str):
            raise ConfigError(
                f"selected_character_id must be a string, got {type(selected).__name__}",
                path=str(self.path),
            )
        language = raw.get("language", DEFAULT_LANGUAGE)
        if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
            raise ConfigError(
                f"Invalid Assistant config language: {language!r}",
                path=str(self.path),
            )
        return AssistantConfig(
            selected_character_id=selected.strip(),
            language=language,
        )

    @staticmethod
    def _to_raw(config: AssistantConfig) -> dict[str, Any]:
        return {
            "selected_character_id": config.selected_character_id,
            "language": config.language,
        }
