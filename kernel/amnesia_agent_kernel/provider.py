"""Provider configuration validation and LiteLLM request helpers."""

import math
from collections.abc import Mapping
from typing import Any, cast

import litellm

from amnesia_agent_kernel.errors import ConfigError, ProviderError
from amnesia_agent_kernel.types import ExecutionPolicy, ProviderConfig


def validate_provider_config(config: ProviderConfig) -> None:
    """Validate provider settings and perform LiteLLM's environment check."""
    if not isinstance(config, ProviderConfig):
        raise ConfigError("config must be a ProviderConfig instance")
    if not isinstance(config.model, str) or not config.model.strip():
        raise ConfigError("model must be a non-empty string")
    for name in ("api_key", "base_url"):
        value = getattr(config, name)
        if value is not None and not isinstance(value, str):
            raise ConfigError(f"{name} must be a string or None")
    if config.provider_params is not None:
        if not isinstance(config.provider_params, Mapping):
            raise ConfigError("provider_params must be a JSON object or None")
        _snapshot_json_value(config.provider_params, "provider_params")
    try:
        result: Any = litellm.validate_environment(
            config.model,
            api_key=config.api_key,
            api_base=config.base_url,
        )
    except Exception as e:
        raise ProviderError(
            f"LLM config check failed: {type(e).__name__}: {e}", model=config.model
        ) from e
    if not isinstance(result, Mapping):
        raise ProviderError("LLM config check returned an invalid result", model=config.model)
    keys_in_environment = result.get("keys_in_environment", True)
    missing_keys = result.get("missing_keys")
    if not isinstance(keys_in_environment, bool):
        raise ProviderError("LLM config check returned an invalid keys status", model=config.model)
    if missing_keys is not None and (
        not isinstance(missing_keys, (list, tuple))
        or not all(isinstance(key, str) for key in missing_keys)
    ):
        raise ProviderError("LLM config check returned invalid missing keys", model=config.model)
    if not keys_in_environment and missing_keys and config.api_key is None:
        raise ProviderError(
            f"LLM config check failed: set {' or '.join(missing_keys)} "
            "in the environment, or provide credentials in the provider config.",
            model=config.model,
        )


def validate_execution_policy(policy: ExecutionPolicy) -> None:
    """Validate resource and context limits for a session."""
    if not isinstance(policy, ExecutionPolicy):
        raise ConfigError("policy must be an ExecutionPolicy instance")
    if (
        isinstance(policy.command_timeout_seconds, bool)
        or not isinstance(policy.command_timeout_seconds, (int, float))
        or not math.isfinite(policy.command_timeout_seconds)
        or policy.command_timeout_seconds <= 0
    ):
        raise ConfigError("command_timeout_seconds must be a finite positive number")
    for name in (
        "max_command_output_bytes",
        "max_context_message_chars",
    ):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{name} must be a positive integer")


def _snapshot_json_value(value: Any, path: str) -> Any:
    """Validate and defensively copy one JSON-compatible value."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigError(f"{path} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConfigError(f"{path} object keys must be strings")
            copied[key] = _snapshot_json_value(item, f"{path}.{key}")
        return copied
    if isinstance(value, list):
        return [_snapshot_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise ConfigError(f"{path} must contain only JSON-compatible values")


def snapshot_response_format(response_format: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Validate and copy a LiteLLM response format supplied for one turn."""
    if response_format is None:
        return None
    if not isinstance(response_format, Mapping):
        raise ConfigError("response_format must be a JSON object or None")
    return cast(
        dict[str, Any],
        _snapshot_json_value(response_format, "response_format"),
    )


def request_kwargs(config: ProviderConfig, **extra: Any) -> dict[str, Any]:
    """Build LiteLLM kwargs, with kernel-controlled request values winning."""
    kwargs: dict[str, Any] = dict(config.provider_params or {})
    kwargs.update(extra)
    kwargs["model"] = config.model
    if config.api_key is not None:
        kwargs["api_key"] = config.api_key
    if config.base_url is not None:
        kwargs["api_base"] = config.base_url
    return kwargs


def provider_error(error: Exception, config: ProviderConfig) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    return ProviderError(f"LLM request failed: {type(error).__name__}: {error}", model=config.model)
