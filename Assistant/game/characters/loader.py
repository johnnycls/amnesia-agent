"""Load and validate data-only character animation packs."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CharacterError(RuntimeError):
    """Invalid or missing character pack."""


MAX_ANIMATION_FRAMES = 120
MAX_ANIMATION_FPS = 60.0
MAX_IMAGE_DIMENSION = 4096
MAX_ANIMATION_BYTES = 25 * 1024 * 1024
_ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CHARACTER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_FRAME_RE = re.compile(r"^(\d{4})\.png$")
_METADATA_KEYS = frozenset({"id", "display_name", "default_bg", "version"})
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_ANIMATION_KEYS = frozenset({"type", "fps", "loop"})


@dataclass(frozen=True)
class MediaAsset:
    """One static-or-animated PNG sequence.

    ``path`` remains the first frame for compatibility with existing callers.
    All assets are represented on disk as animation directories, even when they
    contain one frame.
    """

    path: str
    kind: str  # "image" for one frame, "animation" for multiple frames
    frames: tuple[str, ...] = ()
    fps: float = 8.0
    loop: bool = True

    def __post_init__(self) -> None:
        if not self.frames:
            object.__setattr__(self, "frames", (self.path,))

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1


@dataclass(frozen=True)
class CharacterPack:
    """Resolved character metadata, animated media assets, and prompt."""

    id: str
    display_name: str
    default_bg: str
    backgrounds: dict[str, MediaAsset]
    expressions: dict[str, MediaAsset]
    prompt: str
    pack_dir: str
    source: str = "bundled"
    version: str = ""

    def portrait_asset(self) -> MediaAsset | None:
        """Prefer the neutral expression as the select-screen portrait."""
        return self.expressions.get("neutral") or next(
            iter(self.expressions.values()), None
        )

    def portrait_path(self) -> str | None:
        """Return the first frame path for compatibility with image callers."""
        asset = self.portrait_asset()
        return asset.path if asset is not None else None


def characters_root() -> str:
    """Directory containing bundled per-character pack folders."""
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


def load_character(
    character_id: str,
    root: str | None = None,
    *,
    source: str = "bundled",
    version: str = "",
) -> CharacterPack:
    """Load and validate one animation-directory pack."""
    if not isinstance(character_id, str) or not character_id:
        raise CharacterError("Character id must be a non-empty directory name")
    if Path(character_id).name != character_id or not _CHARACTER_ID_RE.fullmatch(character_id):
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

    raw = _read_json(meta_path, f"character.json for {character_id}")
    if not isinstance(raw, dict):
        raise CharacterError(f"character.json for {character_id} must be an object")
    unknown = set(raw) - _METADATA_KEYS
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
    if not isinstance(default_bg, str) or not _ASSET_ID_RE.fullmatch(default_bg):
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

    pack_version = raw.get("version")
    if pack_version is None:
        resolved_version = version
    elif not isinstance(pack_version, str) or _VERSION_RE.fullmatch(pack_version) is None:
        raise CharacterError(
            f"character.json version for {character_id} must be semantic major.minor.patch"
        )
    else:
        resolved_version = pack_version

    return CharacterPack(
        id=character_id,
        display_name=display_name.strip(),
        default_bg=default_bg,
        backgrounds=backgrounds,
        expressions=expressions,
        prompt=prompt,
        pack_dir=os.path.abspath(pack_dir),
        source=source,
        version=resolved_version,
    )


def load_all_characters(root: str | None = None) -> list[CharacterPack]:
    """Load every pack under a root, failing loudly for developer content."""
    return [load_character(cid, root=root) for cid in list_character_ids(root)]


def load_character_root_safely(
    root: str,
    *,
    source: str,
    versions: dict[str, str] | None = None,
) -> tuple[list[CharacterPack], list[str]]:
    """Load valid packs while isolating invalid community packs."""
    packs: list[CharacterPack] = []
    errors: list[str] = []
    for character_id in list_character_ids(root):
        try:
            packs.append(
                load_character(
                    character_id,
                    root=root,
                    source=source,
                    version=(versions or {}).get(character_id, ""),
                )
            )
        except CharacterError as error:
            errors.append(f"{character_id}: {error}")
    return packs, errors


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
        if not path.is_dir():
            raise CharacterError(
                f"{kind} {path.name!r} must be an animation directory for {character_id}"
            )
        asset_id = path.name
        if not _ASSET_ID_RE.fullmatch(asset_id):
            raise CharacterError(f"Invalid {kind} id for {character_id}: {asset_id}")
        if asset_id in assets:
            raise CharacterError(
                f"Duplicate {kind} id {asset_id!r} for {character_id}"
            )

        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(pack_root)
        except ValueError as error:
            raise CharacterError(
                f"{kind} asset escapes character pack for {character_id}: {path.name}"
            ) from error
        assets[asset_id] = _load_animation(
            resolved, kind, character_id, require_alpha=require_alpha
        )

    if not assets:
        raise CharacterError(f"No {kind} assets found in {directory} for {character_id}")
    return assets


def _load_animation(
    directory: Path,
    asset_kind: str,
    character_id: str,
    *,
    require_alpha: bool,
) -> MediaAsset:
    metadata_path = directory / "animation.json"
    if not metadata_path.is_file():
        raise CharacterError(
            f"Missing animation.json for {asset_kind} {directory.name!r} "
            f"in {character_id}"
        )
    raw = _read_json(
        os.fspath(metadata_path),
        f"animation.json for {asset_kind} {directory.name!r} in {character_id}",
    )
    if not isinstance(raw, dict):
        raise CharacterError(f"animation.json for {directory.name} must be an object")
    unknown = set(raw) - _ANIMATION_KEYS
    if unknown:
        raise CharacterError(
            f"animation.json for {directory.name} has unsupported property: "
            f"{next(iter(unknown))}"
        )
    if raw.get("type") != "png_sequence":
        raise CharacterError(f"Unsupported animation type for {directory.name}")
    fps = raw.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)):
        raise CharacterError(f"Invalid fps for {directory.name}")
    if not math.isfinite(float(fps)) or fps <= 0 or fps > MAX_ANIMATION_FPS:
        raise CharacterError(
            f"fps for {directory.name} must be between 0 and {MAX_ANIMATION_FPS:g}"
        )
    loop = raw.get("loop")
    if not isinstance(loop, bool):
        raise CharacterError(f"Invalid loop for {directory.name}")

    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise CharacterError(f"Cannot list animation {directory.name}: {error}") from error

    frame_paths: list[Path] = []
    for path in entries:
        if path.name == "animation.json":
            continue
        if not path.is_file() or path.suffix.lower() != ".png":
            raise CharacterError(
                f"Invalid frame in {directory.name}: {path.name}"
            )
        frame_paths.append(path)

    if not frame_paths:
        raise CharacterError(f"No PNG frames found for {directory.name}")
    if len(frame_paths) > MAX_ANIMATION_FRAMES:
        raise CharacterError(
            f"Animation {directory.name} has too many frames "
            f"(maximum {MAX_ANIMATION_FRAMES})"
        )

    numbered: list[tuple[int, Path]] = []
    for path in frame_paths:
        match = _FRAME_RE.fullmatch(path.name)
        if match is None:
            raise CharacterError(
                f"Frame {path.name!r} in {directory.name} must use 0001.png naming"
            )
        numbered.append((int(match.group(1)), path))
    numbered.sort()
    expected = list(range(1, len(numbered) + 1))
    if [number for number, _ in numbered] != expected:
        raise CharacterError(f"Animation {directory.name} frame numbers must be consecutive")

    total_bytes = 0
    dimensions: tuple[int, int, bool] | None = None
    resolved_frames: list[str] = []
    pack_root = directory.parent.parent.resolve()
    for _, path in numbered:
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(pack_root)
        except ValueError as error:
            raise CharacterError(
                f"{asset_kind} frame escapes character pack for {character_id}: {path.name}"
            ) from error
        total_bytes += resolved.stat().st_size
        if total_bytes > MAX_ANIMATION_BYTES:
            raise CharacterError(
                f"Animation {directory.name} exceeds {MAX_ANIMATION_BYTES} bytes"
            )
        info = _validate_png(
            resolved, asset_kind, character_id, require_alpha=require_alpha
        )
        if dimensions is None:
            dimensions = info
        elif info != dimensions:
            raise CharacterError(
                f"All frames in {directory.name} must share dimensions and transparency"
            )
        resolved_frames.append(os.fspath(resolved))

    return MediaAsset(
        path=resolved_frames[0],
        kind="image" if len(resolved_frames) == 1 else "animation",
        frames=tuple(resolved_frames),
        fps=float(fps),
        loop=loop,
    )


def _read_json(path: str, description: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CharacterError(f"Cannot read {description}: {error}") from error


def _validate_png(
    path: Path,
    asset_kind: str,
    character_id: str,
    *,
    require_alpha: bool,
) -> tuple[int, int, bool]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise CharacterError(
            f"Cannot read {asset_kind} frame for {character_id}: {path.name}: {error}"
        ) from error
    if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CharacterError(
            f"Invalid PNG {asset_kind} frame for {character_id}: {path.name}"
        )
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0 or max(width, height) > MAX_IMAGE_DIMENSION:
        raise CharacterError(
            f"PNG frame dimensions exceed {MAX_IMAGE_DIMENSION} for {character_id}: "
            f"{path.name}"
        )
    color_type = data[25]
    has_alpha = color_type in (4, 6) or _png_has_trns(data)
    if require_alpha and not has_alpha:
        raise CharacterError(
            f"{asset_kind.capitalize()} frame must contain transparency for "
            f"{character_id}: {path.name}"
        )
    return width, height, has_alpha


def _png_has_trns(data: bytes) -> bool:
    offset = 8
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type == b"tRNS":
            return True
        offset += 12 + length
    return False
