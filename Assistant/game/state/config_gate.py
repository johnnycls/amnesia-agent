"""Provider + character readiness checks for Assistant boot/config gate."""

from __future__ import annotations

from collections.abc import Collection
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


def is_character_selected(
    selected_character_id: str, available_ids: Collection[str]
) -> bool:
    """True when a non-empty id is set and still present in bundled packs."""
    if not isinstance(selected_character_id, str):
        return False
    cid = selected_character_id.strip()
    return bool(cid) and cid in available_ids


def next_setup_page(*, provider_ok: bool, character_ok: bool) -> str | None:
    """Return ``None`` when ready for Main, else ``config`` or ``character_select``.

    Prefer Config when server credentials are missing; otherwise Character Select.
    """
    if provider_ok and character_ok:
        return None
    if not provider_ok:
        return "config"
    return "character_select"


def is_boot_ready(*, provider_ok: bool, character_ok: bool) -> bool:
    return provider_ok and character_ok
