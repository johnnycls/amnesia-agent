"""Frontend-owned configuration storage and validation."""

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
)

DEFAULT_CONFIG_DIR = Path.home() / ".amnesia-agent-cli"
PACKAGED_CONFIG_RESOURCE = "amnesia_agent_cli/data/config.json"
CONFIG_KEYS = frozenset(
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


@dataclass(frozen=True)
class LoadedConfig:
    """The provider settings and execution policy loaded by the CLI."""

    provider: ProviderConfig
    policy: ExecutionPolicy


def _packaged_config() -> Any:
    return files("amnesia_agent_cli").joinpath("data", "config.json")


def _blank_as_none(value: Any) -> Any:
    return None if value == "" else value


class ConfigStore:
    """Persistent CLI configuration, separate from the kernel workspace."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        if root is not None and (
            isinstance(root, bool) or not isinstance(root, (str, os.PathLike))
        ):
            raise ConfigError(f"Invalid config root {root!r}")
        if root == "":
            raise ConfigError("Config root must not be empty.")
        try:
            resolved = (
                Path(root).expanduser().absolute() if root is not None else DEFAULT_CONFIG_DIR
            )
        except (OSError, TypeError, ValueError) as e:
            raise ConfigError(f"Invalid config root {root!r}: {e}") from e
        self.root = resolved

    @property
    def path(self) -> Path:
        return self.root / "config.json"

    def setup(self) -> None:
        """Create the config directory and seed a missing config file."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                shutil.copyfile(str(_packaged_config()), self.path)
        except (ModuleNotFoundError, OSError, TypeError, ValueError) as e:
            raise ConfigError(
                f"Cannot initialize config {self.path} from packaged resource "
                f"{PACKAGED_CONFIG_RESOURCE}: {e}",
                path=str(self.path),
            ) from e

    def reset(self) -> None:
        """Restore the packaged default config file."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(_packaged_config()), self.path)
        except (ModuleNotFoundError, OSError, TypeError, ValueError) as e:
            raise ConfigError(
                f"Cannot reset config {self.path} from packaged resource "
                f"{PACKAGED_CONFIG_RESOURCE}: {e}",
                path=str(self.path),
            ) from e

    def load(self) -> LoadedConfig:
        """Load and validate CLI settings without contacting the provider."""
        if not self.path.exists():
            self.setup()
        try:
            with self.path.open(encoding="utf-8-sig") as f:
                raw_value: Any = json.load(f)
        except OSError as e:
            raise ConfigError(f"Cannot read file {self.path}: {e}", path=str(self.path)) from e
        except (UnicodeError, json.JSONDecodeError) as e:
            raise ConfigError(f"Malformed JSON in {self.path}: {e}", path=str(self.path)) from e

        return self._parse(raw_value)

    def _parse(self, raw_value: Any) -> LoadedConfig:
        if not isinstance(raw_value, dict):
            raise ConfigError("config.json must contain a JSON object.", path=str(self.path))
        unknown = set(raw_value) - CONFIG_KEYS
        if unknown:
            name = next(iter(unknown))
            raise ConfigError(
                f"Invalid config.json at {name}: unexpected property",
                path=str(self.path),
            )
        raw = raw_value
        provider = ProviderConfig(
            model=cast(str, raw.get("model")),
            api_key=_blank_as_none(raw.get("api_key")),
            base_url=_blank_as_none(raw.get("base_url")),
            provider_params=raw.get("provider_params"),
        )
        policy = ExecutionPolicy(
            command_timeout_seconds=raw.get("command_timeout_seconds", 1800.0),
            max_command_output_bytes=raw.get("max_command_output_bytes", 256 * 1024),
            max_context_message_chars=raw.get("max_context_message_chars", 1000),
        )
        # Structural checks only — LiteLLM env/credential preflight runs when
        # KernelSession is constructed, not on config load.
        if not isinstance(provider.model, str) or not provider.model.strip():
            raise ConfigError("model must be a non-empty string", path=str(self.path))
        try:
            validate_execution_policy(policy)
        except ConfigError as e:
            raise ConfigError(str(e), path=str(self.path)) from e
        return LoadedConfig(provider=provider, policy=policy)
