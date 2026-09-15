"""Persistent configuration owned by the local server."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from amnesia_agent_kernel import (
    ConfigError,
    ExecutionPolicy,
    ProviderConfig,
    ProviderError,
    validate_execution_policy,
    validate_provider_config,
)

DEFAULT_CONFIG_DIR = Path.home() / ".amnesia-agent-local-server"

# Importable defaults (also used to seed / reset the persisted file).
DEFAULT_MODEL: Final[str] = ""
DEFAULT_API_KEY: Final[str] = ""
DEFAULT_BASE_URL: Final[str] = ""
DEFAULT_PROVIDER_PARAMS: Final[dict[str, Any]] = {}
DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[float] = 1800.0
DEFAULT_MAX_COMMAND_OUTPUT_BYTES: Final[int] = 256 * 1024
DEFAULT_MAX_CONTEXT_MESSAGE_CHARS: Final[int] = 1000

CONFIG_FIELDS: Final[tuple[str, ...]] = (
    "model",
    "api_key",
    "base_url",
    "provider_params",
    "command_timeout_seconds",
    "max_command_output_bytes",
    "max_context_message_chars",
)
_CONFIG_KEYS = frozenset(CONFIG_FIELDS)


def default_config_dict() -> dict[str, Any]:
    """Return a fresh JSON-serializable defaults dict from constants."""
    return {
        "model": DEFAULT_MODEL,
        "api_key": DEFAULT_API_KEY,
        "base_url": DEFAULT_BASE_URL,
        "provider_params": dict(DEFAULT_PROVIDER_PARAMS),
        "command_timeout_seconds": DEFAULT_COMMAND_TIMEOUT_SECONDS,
        "max_command_output_bytes": DEFAULT_MAX_COMMAND_OUTPUT_BYTES,
        "max_context_message_chars": DEFAULT_MAX_CONTEXT_MESSAGE_CHARS,
    }


def _blank_as_none(value: Any) -> Any:
    return None if value == "" else value


def _resolve_root(root: str | os.PathLike[str] | None) -> Path:
    if root is None:
        return DEFAULT_CONFIG_DIR.resolve(strict=False)
    if isinstance(root, bool) or not isinstance(root, (str, os.PathLike)):
        raise ConfigError(f"Invalid config root {root!r}")
    if root == "":
        raise ConfigError("Config root must not be empty.")
    try:
        return Path(root).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError) as error:
        raise ConfigError(f"Invalid config root {root!r}: {error}") from error


def _atomic_write_json(path: Path, raw: dict[str, Any]) -> None:
    """Atomically write JSON then tighten file mode (``0o600`` on Unix)."""
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        if os.name == "nt":
            # NTFS ignores full POSIX modes; best-effort clear read-only only.
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        else:
            os.chmod(path, 0o600)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConfigError(f"Cannot write config {path}: {error}", path=str(path)) from error


@dataclass(frozen=True)
class LoadedConfig:
    """Validated provider settings and execution policy."""

    provider: ProviderConfig
    policy: ExecutionPolicy


def resolve_request_workspace_path(value: str | None) -> str | None:
    """Map a request ``workspace_path`` to a KernelSession ``workspace_root``.

    Omit/``None``/empty string → ``None`` (kernel default ``~/.amnesia-agent``).
    Non-blank strings are passed through; expanduser happens in the kernel.
    """
    if value is None or value == "":
        return None
    return value


def config_to_raw(config: LoadedConfig) -> dict[str, Any]:
    """Serialize a loaded config to the on-disk JSON object shape."""
    return {
        "model": config.provider.model,
        "api_key": config.provider.api_key or "",
        "base_url": config.provider.base_url or "",
        "provider_params": dict(config.provider.provider_params or {}),
        "command_timeout_seconds": config.policy.command_timeout_seconds,
        "max_command_output_bytes": config.policy.max_command_output_bytes,
        "max_context_message_chars": config.policy.max_context_message_chars,
    }


class ConfigStore:
    """Load, save, and reset ``~/.amnesia-agent-local-server/config.json``."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = _resolve_root(root)

    @property
    def path(self) -> Path:
        return self.root / "config.json"

    def _atomic_write(self, raw: dict[str, Any]) -> None:
        _atomic_write_json(self.path, raw)

    def write_defaults(self) -> None:
        """Rewrite ``config.json`` from importable defaults constants."""
        self._atomic_write(default_config_dict())

    def setup(self) -> None:
        """Seed a missing configuration file from defaults constants."""
        if not self.path.exists():
            self.write_defaults()

    def reset(self) -> LoadedConfig:
        """Rewrite defaults from constants and return the validated result."""
        self.write_defaults()
        return self.load()

    def load(self) -> LoadedConfig:
        """Load and validate the JSON configuration.

        A missing file is lazy-created from defaults constants. Corrupt or
        invalid files raise ``ConfigError`` (no auto-repair).
        """
        if not self.path.exists():
            self.write_defaults()
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
        self._atomic_write(config_to_raw(config))

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
            model=cast(str, raw.get("model", DEFAULT_MODEL)),
            api_key=_blank_as_none(raw.get("api_key", DEFAULT_API_KEY)),
            base_url=_blank_as_none(raw.get("base_url", DEFAULT_BASE_URL)),
            provider_params=raw.get("provider_params", dict(DEFAULT_PROVIDER_PARAMS)),
        )
        policy = ExecutionPolicy(
            command_timeout_seconds=raw.get(
                "command_timeout_seconds", DEFAULT_COMMAND_TIMEOUT_SECONDS
            ),
            max_command_output_bytes=raw.get(
                "max_command_output_bytes", DEFAULT_MAX_COMMAND_OUTPUT_BYTES
            ),
            max_context_message_chars=raw.get(
                "max_context_message_chars", DEFAULT_MAX_CONTEXT_MESSAGE_CHARS
            ),
        )
        try:
            _validate_provider(provider)
            validate_execution_policy(policy)
        except ConfigError as error:
            raise ConfigError(str(error), path=str(self.path)) from error
        return LoadedConfig(
            provider=provider,
            policy=policy,
        )


def _validate_provider(provider: ProviderConfig) -> None:
    """Validate provider fields for persistence.

    Blank model is checked as ``unconfigured`` so the settings UI can persist an
    incomplete initial config. Missing API keys are allowed here so clients can
    clear credentials; ``KernelSession`` still validates before a turn.
    """
    if isinstance(provider.model, str) and not provider.model.strip():
        provider = ProviderConfig(
            model="unconfigured",
            api_key=provider.api_key,
            base_url=provider.base_url,
            provider_params=provider.provider_params,
        )
    try:
        validate_provider_config(provider)
    except ProviderError as error:
        if provider.api_key is None and "provide credentials" in str(error):
            return
        raise


# Credential-shaped keys rejected from provider_params on write and redacted on
# public reads. Prefer top-level ``api_key`` / ``base_url`` for secrets.
_CREDENTIAL_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "api_base",
        "token",
        "secret",
        "password",
        "authorization",
        "access_token",
        "refresh_token",
    }
)
REDACTED_SENTINEL: Final[str] = "***"


def _normalize_param_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _is_credential_param_key(key: str) -> bool:
    return _normalize_param_key(key) in _CREDENTIAL_PARAM_KEYS


def redact_provider_params(params: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy *params*, replacing credential-shaped values with ``***``.

    Credential keys (case-insensitive, ``-``/``_`` normalized): ``api_key``,
    ``api_base``, ``token``, ``secret``, ``password``, ``authorization``,
    ``access_token``, ``refresh_token``. Nested ``extra_headers`` values are
    always replaced with the sentinel (header values may carry Bearer tokens).
    Other nested dicts are walked recursively; lists are copied element-wise.
    Non-dict top-level input is returned as an empty dict.
    """
    if not isinstance(params, dict):
        return {}
    return _redact_mapping(params, under_extra_headers=False)


def _redact_mapping(params: dict[str, Any], *, under_extra_headers: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        key_str = str(key)
        if under_extra_headers or _is_credential_param_key(key_str):
            out[key_str] = REDACTED_SENTINEL
            continue
        if _normalize_param_key(key_str) == "extra_headers" and isinstance(value, dict):
            out[key_str] = _redact_mapping(value, under_extra_headers=True)
            continue
        if isinstance(value, dict):
            out[key_str] = _redact_mapping(value, under_extra_headers=False)
        elif isinstance(value, list):
            out[key_str] = [
                _redact_mapping(item, under_extra_headers=False) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            out[key_str] = value
    return out


def find_credential_provider_param_paths(params: dict[str, Any]) -> list[str]:
    """Return dotted paths of credential-shaped keys in *params* (for errors)."""
    if not isinstance(params, dict):
        return []
    found: list[str] = []
    _collect_credential_paths(params, prefix="", found=found, under_extra_headers=False)
    return found


def _collect_credential_paths(
    params: dict[str, Any],
    *,
    prefix: str,
    found: list[str],
    under_extra_headers: bool,
) -> None:
    for key, value in params.items():
        key_str = str(key)
        path = f"{prefix}.{key_str}" if prefix else key_str
        # Under extra_headers, only credential-shaped header names are forbidden
        # on write; public reads still redact *all* extra_headers values.
        if _is_credential_param_key(key_str):
            found.append(path)
            continue
        if under_extra_headers:
            continue
        if _normalize_param_key(key_str) == "extra_headers" and isinstance(value, dict):
            _collect_credential_paths(value, prefix=path, found=found, under_extra_headers=True)
            continue
        if isinstance(value, dict):
            _collect_credential_paths(value, prefix=path, found=found, under_extra_headers=False)


def reject_provider_params_secrets(params: dict[str, Any]) -> None:
    """Raise ``ConfigError`` if *params* contains credential-shaped keys.

    Clients must store secrets in top-level ``api_key`` / ``base_url``, not in
    ``provider_params`` (which is shown in frontend config forms).
    """
    if params is None:
        return
    if not isinstance(params, dict):
        raise ConfigError("provider_params must be a JSON object.")
    bad = find_credential_provider_param_paths(params)
    if bad:
        raise ConfigError(
            "provider_params must not contain credential keys "
            f"({', '.join(bad)}). Use top-level api_key / base_url instead."
        )


def public_config(config: LoadedConfig) -> dict[str, Any]:
    """Return config safe for clients; never disclose secrets.

    ``api_key`` is always ``null`` with ``api_key_set`` indicating presence.
    ``provider_params`` is deep-redacted via ``redact_provider_params``.
    """
    raw = config_to_raw(config)
    return {
        "model": raw["model"],
        "api_key": None,
        "api_key_set": config.provider.api_key is not None,
        "base_url": raw["base_url"] or None,
        "provider_params": redact_provider_params(raw["provider_params"]),
        "command_timeout_seconds": raw["command_timeout_seconds"],
        "max_command_output_bytes": raw["max_command_output_bytes"],
        "max_context_message_chars": raw["max_context_message_chars"],
    }
