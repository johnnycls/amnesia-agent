"""Persistent configuration owned by the local server."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from amnesia_agent_kernel import (
    ConfigError,
    ExecutionPolicy,
    ProviderConfig,
    validate_execution_policy,
    validate_provider_config,
)

DEFAULT_CONFIG_DIR = Path.home() / ".amnesia-agent-local-server"
_CONFIG_KEYS = frozenset(
    {
        "model",
        "api_key",
        "base_url",
        "provider_params",
        "command_timeout_seconds",
        "max_command_output_bytes",
        "max_context_message_chars",
    }
)


def _packaged_config() -> Any:
    return files("amnesia_agent_local_server").joinpath("data", "config.json")


def _blank_as_none(value: Any) -> Any:
    return None if value == "" else value


@dataclass(frozen=True)
class LoadedConfig:
    """Validated provider settings and execution policy."""

    provider: ProviderConfig
    policy: ExecutionPolicy


class ConfigStore:
    """Load, save, and reset ``~/.amnesia-agent-local-server/config.json``."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        if root is not None and (
            isinstance(root, bool) or not isinstance(root, (str, os.PathLike))
        ):
            raise ConfigError(f"Invalid config root {root!r}")
        if root == "":
            raise ConfigError("Config root must not be empty.")
        try:
            self.root = (
                Path(root).expanduser().absolute() if root is not None else DEFAULT_CONFIG_DIR
            )
        except (OSError, TypeError, ValueError) as error:
            raise ConfigError(f"Invalid config root {root!r}: {error}") from error

    @property
    def path(self) -> Path:
        return self.root / "config.json"

    def setup(self) -> None:
        """Create the directory and seed a missing configuration file."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                shutil.copyfile(str(_packaged_config()), self.path)
        except (ModuleNotFoundError, OSError, TypeError, ValueError) as error:
            raise ConfigError(
                f"Cannot initialize config {self.path}: {error}", path=str(self.path)
            ) from error

    def reset(self) -> LoadedConfig:
        """Restore packaged defaults and return the validated result."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(_packaged_config()), self.path)
        except (ModuleNotFoundError, OSError, TypeError, ValueError) as error:
            raise ConfigError(
                f"Cannot reset config {self.path}: {error}", path=str(self.path)
            ) from error
        return self.load()

    def load(self) -> LoadedConfig:
        """Load and validate the JSON configuration.

        A missing file is lazy-created from packaged defaults. Corrupt or invalid
        files raise ``ConfigError`` (no auto-repair).
        """
        if not self.path.exists():
            self.setup()
        try:
            with self.path.open(encoding="utf-8-sig") as file:
                raw_value: Any = json.load(file)
        except OSError as error:
            raise ConfigError(
                f"Cannot read file {self.path}: {error}", path=str(self.path)
            ) from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ConfigError(
                f"Malformed JSON in {self.path}: {error}", path=str(self.path)
            ) from error
        return self._parse(raw_value)

    def save(self, config: LoadedConfig) -> None:
        """Validate and atomically persist a configuration snapshot."""
        _validate_provider(config.provider)
        validate_execution_policy(config.policy)
        raw = {
            "model": config.provider.model,
            "api_key": config.provider.api_key or "",
            "base_url": config.provider.base_url or "",
            "provider_params": dict(config.provider.provider_params or {}),
            "command_timeout_seconds": config.policy.command_timeout_seconds,
            "max_command_output_bytes": config.policy.max_command_output_bytes,
            "max_context_message_chars": config.policy.max_context_message_chars,
        }
        temporary = self.path.with_suffix(".tmp")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ConfigError(
                f"Cannot write config {self.path}: {error}", path=str(self.path)
            ) from error

    def _parse(self, raw_value: Any) -> LoadedConfig:
        if not isinstance(raw_value, dict):
            raise ConfigError("config.json must contain a JSON object.", path=str(self.path))
        unknown = set(raw_value) - _CONFIG_KEYS
        if unknown:
            name = next(iter(unknown))
            raise ConfigError(
                f"Invalid config.json at {name}: unexpected property", path=str(self.path)
            )
        raw = raw_value
        provider = ProviderConfig(
            model=cast(str, raw.get("model", "")),
            api_key=_blank_as_none(raw.get("api_key")),
            base_url=_blank_as_none(raw.get("base_url")),
            provider_params=raw.get("provider_params"),
        )
        policy = ExecutionPolicy(
            command_timeout_seconds=raw.get("command_timeout_seconds", 120.0),
            max_command_output_bytes=raw.get("max_command_output_bytes", 256 * 1024),
            max_context_message_chars=raw.get("max_context_message_chars", 1000),
        )
        try:
            _validate_provider(provider)
            validate_execution_policy(policy)
        except ConfigError as error:
            raise ConfigError(str(error), path=str(self.path)) from error
        return LoadedConfig(provider=provider, policy=policy)


def _validate_provider(provider: ProviderConfig) -> None:
    """Validate provider fields while permitting the initial blank model."""
    if isinstance(provider.model, str) and not provider.model.strip():
        provider = ProviderConfig(
            model="unconfigured",
            api_key=provider.api_key,
            base_url=provider.base_url,
            provider_params=provider.provider_params,
        )
    validate_provider_config(provider)


def public_config(config: LoadedConfig) -> dict[str, Any]:
    """Return config safe for clients; never disclose the API key."""
    return {
        "model": config.provider.model,
        "api_key": None,
        "api_key_set": config.provider.api_key is not None,
        "base_url": config.provider.base_url,
        "provider_params": dict(config.provider.provider_params or {}),
        "command_timeout_seconds": config.policy.command_timeout_seconds,
        "max_command_output_bytes": config.policy.max_command_output_bytes,
        "max_context_message_chars": config.policy.max_context_message_chars,
    }
