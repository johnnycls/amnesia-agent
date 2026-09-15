"""Load bundled character packs from game/characters/<id>/."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


class CharacterError(RuntimeError):
    """Invalid or missing character pack."""


@dataclass(frozen=True)
class CharacterPack:
    """Resolved character assets and prompt for the UI."""

    id: str
    display_name: str
    default_bg: str
    default_expression: str
    backgrounds: dict[str, str]  # id -> absolute path
    expressions: dict[str, str]  # id -> absolute path
    prompt: str
    pack_dir: str

    def portrait_path(self) -> str | None:
        """Prefer neutral expression as select-screen portrait."""
        return self.expressions.get("neutral") or next(
            iter(self.expressions.values()), None
        )


def characters_root() -> str:
    """Directory containing per-character pack folders."""
    return os.path.dirname(os.path.abspath(__file__))


def list_character_ids(root: str | None = None) -> list[str]:
    """Return sorted pack ids that contain character.json."""
    base = root if root is not None else characters_root()
    ids: list[str] = []
    try:
        entries = os.listdir(base)
    except OSError as error:
        raise CharacterError(f"Cannot list characters directory: {error}") from error
    for name in sorted(entries):
        pack_dir = os.path.join(base, name)
        if not os.path.isdir(pack_dir):
            continue
        if os.path.isfile(os.path.join(pack_dir, "character.json")):
            ids.append(name)
    return ids


def load_character(character_id: str, root: str | None = None) -> CharacterPack:
    """Load and validate one pack; fail loud on missing/invalid data."""
    base = root if root is not None else characters_root()
    pack_dir = os.path.join(base, character_id)
    meta_path = os.path.join(pack_dir, "character.json")
    prompt_path = os.path.join(pack_dir, "prompt.md")

    if not os.path.isdir(pack_dir):
        raise CharacterError(f"Character pack not found: {character_id}")
    if not os.path.isfile(meta_path):
        raise CharacterError(f"Missing character.json for {character_id}")
    if not os.path.isfile(prompt_path):
        raise CharacterError(f"Missing prompt.md for {character_id}")

    try:
        with open(meta_path, encoding="utf-8") as handle:
            raw: Any = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise CharacterError(
            f"Cannot read character.json for {character_id}: {error}"
        ) from error

    if not isinstance(raw, dict):
        raise CharacterError(f"character.json for {character_id} must be an object")

    pack_id = raw.get("id")
    display_name = raw.get("display_name")
    default_bg = raw.get("default_bg")
    default_expression = raw.get("default_expression")
    backgrounds_raw = raw.get("backgrounds")
    expressions_raw = raw.get("expressions")

    if pack_id != character_id:
        raise CharacterError(
            f"character.json id {pack_id!r} does not match folder {character_id!r}"
        )
    if not isinstance(display_name, str) or not display_name.strip():
        raise CharacterError(f"Invalid display_name for {character_id}")
    if not isinstance(default_bg, str) or not default_bg:
        raise CharacterError(f"Invalid default_bg for {character_id}")
    if not isinstance(default_expression, str) or not default_expression:
        raise CharacterError(f"Invalid default_expression for {character_id}")
    if not isinstance(backgrounds_raw, dict) or not backgrounds_raw:
        raise CharacterError(f"backgrounds must be a non-empty object for {character_id}")
    if not isinstance(expressions_raw, dict) or not expressions_raw:
        raise CharacterError(f"expressions must be a non-empty object for {character_id}")
    if default_bg not in backgrounds_raw:
        raise CharacterError(
            f"default_bg {default_bg!r} missing from backgrounds for {character_id}"
        )
    if default_expression not in expressions_raw:
        raise CharacterError(
            f"default_expression {default_expression!r} missing from expressions "
            f"for {character_id}"
        )

    backgrounds = _resolve_asset_map(pack_dir, backgrounds_raw, "background", character_id)
    expressions = _resolve_asset_map(
        pack_dir, expressions_raw, "expression", character_id
    )

    try:
        with open(prompt_path, encoding="utf-8") as handle:
            prompt = handle.read()
    except OSError as error:
        raise CharacterError(
            f"Cannot read prompt.md for {character_id}: {error}"
        ) from error
    if not prompt.strip():
        raise CharacterError(f"prompt.md is empty for {character_id}")

    return CharacterPack(
        id=character_id,
        display_name=display_name.strip(),
        default_bg=default_bg,
        default_expression=default_expression,
        backgrounds=backgrounds,
        expressions=expressions,
        prompt=prompt,
        pack_dir=pack_dir,
    )


def load_all_characters(root: str | None = None) -> list[CharacterPack]:
    """Load every pack under the characters root."""
    return [load_character(cid, root=root) for cid in list_character_ids(root)]


def _resolve_asset_map(
    pack_dir: str,
    mapping: dict[str, Any],
    kind: str,
    character_id: str,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, rel in mapping.items():
        if not isinstance(key, str) or not key:
            raise CharacterError(f"Invalid {kind} id in {character_id}")
        if not isinstance(rel, str) or not rel:
            raise CharacterError(
                f"Invalid {kind} path for {key!r} in {character_id}"
            )
        absolute = os.path.normpath(os.path.join(pack_dir, rel))
        if not os.path.isfile(absolute):
            raise CharacterError(
                f"Missing {kind} file for {character_id}/{key}: {rel}"
            )
        resolved[key] = absolute
    return resolved
