"""Load bundled character packs from game/characters/<id>/."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CharacterError(RuntimeError):
    """Invalid or missing character pack."""


@dataclass(frozen=True)
class MediaAsset:
    """One validated still-image or video asset."""

    path: str
    kind: str  # "image" or "video"


@dataclass(frozen=True)
class CharacterPack:
    """Resolved character metadata, media assets, and prompt."""

    id: str
    display_name: str
    default_bg: str
    backgrounds: dict[str, MediaAsset]
    expressions: dict[str, MediaAsset]
    prompt: str
    pack_dir: str

    def portrait_asset(self) -> MediaAsset | None:
        """Prefer the neutral expression as the select-screen portrait."""
        return self.expressions.get("neutral") or next(
            iter(self.expressions.values()), None
        )

    def portrait_path(self) -> str | None:
        """Return the portrait path for compatibility with image-only callers."""
        asset = self.portrait_asset()
        return asset.path if asset is not None else None


_MEDIA_KINDS = {
    ".png": "image",
    ".webp": "image",
}
_ALLOWED_METADATA_KEYS = frozenset(
    {"id", "display_name", "default_bg"}
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
    """Load and validate one pack; fail loud on missing or invalid data."""
    if not isinstance(character_id, str) or not character_id:
        raise CharacterError("Character id must be a non-empty directory name")
    if Path(character_id).name != character_id:
        raise CharacterError(f"Invalid character id: {character_id!r}")

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
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CharacterError(
            f"Cannot read character.json for {character_id}: {error}"
        ) from error

    if not isinstance(raw, dict):
        raise CharacterError(f"character.json for {character_id} must be an object")
    unknown = set(raw) - _ALLOWED_METADATA_KEYS
    if unknown:
        name = next(iter(unknown))
        raise CharacterError(
            f"character.json for {character_id} has unsupported property: {name}"
        )

    pack_id = raw.get("id")
    display_name = raw.get("display_name")
    default_bg = raw.get("default_bg")

    if pack_id != character_id:
        raise CharacterError(
            f"character.json id {pack_id!r} does not match folder {character_id!r}"
        )
    if not isinstance(display_name, str) or not display_name.strip():
        raise CharacterError(f"Invalid display_name for {character_id}")
    if not isinstance(default_bg, str) or not default_bg:
        raise CharacterError(f"Invalid default_bg for {character_id}")

    backgrounds = _discover_assets(
        pack_dir, "bg", "background", character_id, require_alpha=False
    )
    expressions = _discover_assets(
        pack_dir, "expressions", "expression", character_id, require_alpha=True
    )
    if not backgrounds:
        raise CharacterError(f"Character {character_id} must have at least one bg asset")
    if "neutral" not in expressions or "busy" not in expressions:
        raise CharacterError(
            f"Character {character_id} must have neutral and busy expressions"
        )
    if default_bg not in backgrounds:
        raise CharacterError(
            f"default_bg {default_bg!r} has no matching bg asset for {character_id}"
        )

    try:
        with open(prompt_path, encoding="utf-8") as handle:
            prompt = handle.read()
    except (OSError, UnicodeError) as error:
        raise CharacterError(
            f"Cannot read prompt.md for {character_id}: {error}"
        ) from error
    if not prompt.strip():
        raise CharacterError(f"prompt.md is empty for {character_id}")

    return CharacterPack(
        id=character_id,
        display_name=display_name.strip(),
        default_bg=default_bg,
        backgrounds=backgrounds,
        expressions=expressions,
        prompt=prompt,
        pack_dir=os.path.abspath(pack_dir),
    )


def load_all_characters(root: str | None = None) -> list[CharacterPack]:
    """Load every pack under the characters root."""
    return [load_character(cid, root=root) for cid in list_character_ids(root)]


def _discover_assets(
    pack_dir: str,
    directory_name: str,
    kind: str,
    character_id: str,
    *,
    require_alpha: bool,
) -> dict[str, MediaAsset]:
    directory = Path(pack_dir) / directory_name
    if not directory.is_dir():
        raise CharacterError(f"Missing {directory_name}/ directory for {character_id}")

    pack_root = Path(pack_dir).resolve()
    assets: dict[str, MediaAsset] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise CharacterError(
            f"Cannot list {directory_name}/ for {character_id}: {error}"
        ) from error

    for path in entries:
        if not path.is_file():
            raise CharacterError(
                f"Invalid {kind} entry for {character_id}: {path.name}"
            )
        suffix = path.suffix.lower()
        media_kind = _MEDIA_KINDS.get(suffix)
        if media_kind is None:
            raise CharacterError(
                f"Unsupported {kind} format for {character_id}: {path.name}"
            )
        asset_id = path.stem
        if not asset_id:
            raise CharacterError(f"Invalid {kind} id for {character_id}: {path.name}")
        if asset_id in assets:
            raise CharacterError(
                f"Duplicate {kind} id {asset_id!r} for {character_id}: {path.name}"
            )

        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(pack_root)
        except ValueError as error:
            raise CharacterError(
                f"{kind} asset escapes character pack for {character_id}: {path.name}"
            ) from error
        _validate_media_signature(
            resolved, media_kind, kind, character_id, require_alpha=require_alpha
        )
        assets[asset_id] = MediaAsset(os.fspath(resolved), media_kind)

    if not assets:
        raise CharacterError(f"No {kind} assets found in {directory} for {character_id}")
    return assets


def _validate_media_signature(
    path: Path,
    media_kind: str,
    asset_kind: str,
    character_id: str,
    *,
    require_alpha: bool,
) -> None:
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError as error:
        raise CharacterError(
            f"Cannot read {asset_kind} asset for {character_id}: {path.name}: {error}"
        ) from error

    valid = False
    has_alpha = False
    if path.suffix.lower() == ".png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n")
        if valid and require_alpha:
            has_alpha = _png_has_alpha(path)
    elif path.suffix.lower() == ".webp":
        valid = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
        if valid and require_alpha:
            has_alpha = _webp_has_alpha(path)

    if not valid:
        raise CharacterError(
            f"Invalid {media_kind} {asset_kind} asset for {character_id}: {path.name}"
        )
    if require_alpha and not has_alpha:
        raise CharacterError(
            f"{asset_kind.capitalize()} asset must contain transparency for "
            f"{character_id}: {path.name}"
        )


def _png_has_alpha(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 26 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    color_type = data[25]
    if color_type in (4, 6):
        return True
    offset = 8
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type == b"tRNS":
            return True
        offset += 12 + length
    return False


def _webp_has_alpha(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    # VP8X stores the alpha flag in bit 4 of its flags byte.
    return len(data) >= 21 and data[12:16] == b"VP8X" and bool(data[20] & 0x10)
