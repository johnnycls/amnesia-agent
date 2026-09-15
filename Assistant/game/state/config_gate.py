"""Provider config readiness checks for Assistant (model + api_key)."""

from __future__ import annotations

from typing import Any


def provider_config_gaps(config: dict[str, Any]) -> list[str]:
    """Return missing required fields: ``model`` and/or ``api_key``.

    ``model`` must be a non-empty string. ``api_key`` is required when
    ``api_key_set`` is false (public config never returns the raw key).
    """
    gaps: list[str] = []
    model = config.get("model")
    if not isinstance(model, str) or not model.strip():
        gaps.append("model")
    if not bool(config.get("api_key_set")):
        gaps.append("api_key")
    return gaps


def is_provider_configured(config: dict[str, Any]) -> bool:
    return not provider_config_gaps(config)


def format_config_required_status(gaps: list[str]) -> str:
    if not gaps:
        return "Provider configured"
    labels = {"model": "model", "api_key": "API key"}
    pretty = ", ".join(labels.get(g, g) for g in gaps)
    return f"Configure required settings: {pretty}"
