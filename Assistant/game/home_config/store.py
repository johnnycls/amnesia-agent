"""Persist Assistant preferences in Ren'Py, with a test-only JSON adapter."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from api.client import DEFAULT_SERVER_URL, ServerUrlError, normalize_server_url

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]

DEFAULT_CONFIG_DIR = Path.home() / ".amnesia-agent-assistant"
DEFAULT_LANGUAGE: Final[str] = "english"
SUPPORTED_LANGUAGES: Final[frozenset[str]] = frozenset(
    {"english", "schinese", "tchinese", "japanese", "korean"}
)
_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {"selected_character_id", "language", "server_url"}
)


class ConfigError(RuntimeError):
    """Corrupt or invalid Assistant config (fail loud; no silent repair)."""

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class AssistantConfig:
    selected_character_id: str
    language: str = DEFAULT_LANGUAGE
    server_url: str = DEFAULT_SERVER_URL


def default_config_dict() -> dict[str, Any]:
    return {
        "selected_character_id": "",
        "language": DEFAULT_LANGUAGE,
        "server_url": DEFAULT_SERVER_URL,
    }


class PersistentAssistantConfigStore:
    """Production preference store backed by Ren'Py persistent data."""

    def _persistent(self) -> Any:
        if renpy is None:
            raise ConfigError("Ren'Py persistent storage is unavailable")
        return renpy.store.persistent

    def load(self) -> AssistantConfig:
        persistent = self._persistent()
        selected = getattr(persistent, "selected_character_id", "")
        language = getattr(persistent, "assistant_language", DEFAULT_LANGUAGE)
        if selected is None:
            selected = ""
        if not isinstance(selected, str):
            raise ConfigError("persistent.selected_character_id must be a string")
        if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
            raise ConfigError(f"Invalid persistent assistant language: {language!r}")
        server_url = getattr(persistent, "server_url", DEFAULT_SERVER_URL)
        try:
            server_url = normalize_server_url(server_url)
        except ServerUrlError as error:
            raise ConfigError(f"Invalid persistent server URL: {error}") from error
        return AssistantConfig(
            selected_character_id=selected.strip(),
            language=language,
            server_url=server_url,
        )

    def save(self, config: AssistantConfig) -> None:
        persistent = self._persistent()
        persistent.selected_character_id = config.selected_character_id
        persistent.assistant_language = config.language
        persistent.server_url = config.server_url
        renpy.save_persistent()

    def reset(self) -> AssistantConfig:
        config = AssistantConfig(
            selected_character_id="",
            language=DEFAULT_LANGUAGE,
            server_url=DEFAULT_SERVER_URL,
        )
        self.save(config)
        return config

    def set_selected_character(self, character_id: str) -> AssistantConfig:
        if not isinstance(character_id, str):
            raise ConfigError("selected_character_id must be a string")
        current = self.load()
        updated = AssistantConfig(
            character_id.strip(), current.language, current.server_url
        )
        self.save(updated)
        return updated

    def set_language(self, language: str) -> AssistantConfig:
        if language not in SUPPORTED_LANGUAGES:
            raise ConfigError(f"Unsupported language: {language!r}")
        current = self.load()
        updated = AssistantConfig(
            current.selected_character_id, language, current.server_url
        )
        self.save(updated)
        return updated

    def set_server_url(self, server_url: str) -> AssistantConfig:
        try:
            canonical = normalize_server_url(server_url)
        except ServerUrlError as error:
            raise ConfigError(f"Invalid server URL: {error}") from error
        current = self.load()
        updated = AssistantConfig(
            current.selected_character_id, current.language, canonical
        )
        self.save(updated)
        return updated


def build_config_store() -> PersistentAssistantConfigStore | "AssistantConfigStore":
    """Use Ren'Py persistence in-game and JSON only for non-Ren'Py tests."""
    if renpy is not None:
        return PersistentAssistantConfigStore()
    return AssistantConfigStore()


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
            server_url=config.server_url,
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
            server_url=config.server_url,
        )
        self.save(updated)
        return updated

    def set_server_url(self, server_url: str) -> AssistantConfig:
        try:
            canonical = normalize_server_url(server_url)
        except ServerUrlError as error:
            raise ConfigError(f"Invalid Assistant server URL: {error}") from error
        config = self.load()
        updated = AssistantConfig(
            selected_character_id=config.selected_character_id,
            language=config.language,
            server_url=canonical,
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
        server_url = raw.get("server_url", DEFAULT_SERVER_URL)
        try:
            server_url = normalize_server_url(server_url)
        except ServerUrlError as error:
            raise ConfigError(
                f"Invalid Assistant config server URL: {error}",
                path=str(self.path),
            ) from error
        return AssistantConfig(
            selected_character_id=selected.strip(),
            language=language,
            server_url=server_url,
        )

    @staticmethod
    def _to_raw(config: AssistantConfig) -> dict[str, Any]:
        return {
            "selected_character_id": config.selected_character_id,
            "language": config.language,
            "server_url": config.server_url,
        }
