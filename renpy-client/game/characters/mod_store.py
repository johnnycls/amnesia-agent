"""Safe one-file .amod installation and user-mod storage."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from characters.loader import load_character

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_FILES = 512
_MOD_FORMAT = "amnesia-character"
_MANIFEST_KEYS = frozenset(
    {
        "format",
        "schema_version",
        "id",
        "version",
        "display_name",
        "author",
        "description",
        "license",
        "content_rating",
        "min_assistant_version",
    }
)
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_ALLOWED_ROOT_FILES = frozenset(
    {"manifest.json", "character.json", "prompt.md", "README.md", "LICENSE"}
)
_ALLOWED_ROOT_DIRS = frozenset({"bg", "bgm", "expressions"})


class ModError(RuntimeError):
    """An archive cannot be safely installed."""


@dataclass(frozen=True)
class ModManifest:
    id: str
    version: str
    display_name: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class InstallResult:
    """Outcome for one explicitly selected archive.

    The caller owns the selected temporary file and must remove it after this
    result is returned. ``installed`` is true only when this archive became the
    live install. An older archive is a successful no-op with a ``note``.
    """

    archive: str
    mod_id: str | None
    version: str | None
    installed: bool
    error: str = ""
    note: str = ""


@dataclass
class _Candidate:
    archive: Path
    manifest: ModManifest
    staged_dir: Path
    staging_root: Path


def default_mods_root() -> Path:
    """Return the per-user mod root, using Ren'Py's save directory in-game."""
    try:
        import renpy  # type: ignore[import-not-found]

        savedir = getattr(getattr(renpy, "config", None), "savedir", None)
        if savedir:
            return Path(savedir) / "mods"
    except ImportError:
        pass
    return Path.home() / ".amnesia-agent-assistant" / "mods"


class ModStore:
    """Deep module for validated, transactional character-mod storage."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root).expanduser().resolve(strict=False) if root else default_mods_root()
        self.staging = self.root / ".staging"
        self.installed = self.root / "installed"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.staging.mkdir(parents=True, exist_ok=True)
        self.installed.mkdir(parents=True, exist_ok=True)

    @property
    def installed_root(self) -> str:
        return os.fspath(self.installed)

    def install_selected_archive(
        self,
        archive: str | os.PathLike[str],
        reserved_ids: set[str] | None = None,
    ) -> InstallResult:
        """Validate and activate exactly one explicitly selected archive.

        This method never scans ``staging`` or any other directory and never
        writes an adjacent error report. The caller owns and cleans up
        ``archive`` after the result is returned.
        """
        source = Path(archive)
        candidate: _Candidate | None = None
        try:
            candidate = self._stage_archive(source)
            manifest = candidate.manifest
            if reserved_ids and manifest.id in reserved_ids:
                raise ModError(
                    f"Mod id {manifest.id!r} conflicts with a bundled character"
                )

            installed = self.installed_manifests().get(manifest.id)
            if installed is not None and _version_key(manifest.version) < _version_key(
                installed.version
            ):
                return InstallResult(
                    archive=os.fspath(source),
                    mod_id=manifest.id,
                    version=manifest.version,
                    installed=False,
                    note=f"superseded by installed {installed.version}",
                )

            self._activate(candidate)
            return InstallResult(
                archive=os.fspath(source),
                mod_id=manifest.id,
                version=manifest.version,
                installed=True,
            )
        except (ModError, OSError, UnicodeError, ValueError, zipfile.BadZipFile) as error:
            return InstallResult(
                archive=os.fspath(source),
                mod_id=candidate.manifest.id if candidate is not None else None,
                version=candidate.manifest.version if candidate is not None else None,
                installed=False,
                error=str(error),
            )
        finally:
            if candidate is not None:
                shutil.rmtree(candidate.staging_root, ignore_errors=True)

    def remove(self, mod_id: str) -> None:
        if not _safe_mod_id(mod_id):
            raise ModError(f"Invalid mod id: {mod_id!r}")
        target = self.installed / mod_id
        if target.exists():
            shutil.rmtree(target)

    def installed_manifests(self) -> dict[str, ModManifest]:
        manifests: dict[str, ModManifest] = {}
        for directory in sorted(self.installed.iterdir(), key=lambda p: p.name.lower()):
            if not directory.is_dir():
                continue
            path = directory / "manifest.json"
            if not path.is_file():
                continue
            try:
                manifest = _parse_manifest(_read_json(path))
            except (ModError, OSError, UnicodeError, json.JSONDecodeError):
                continue
            manifests[manifest.id] = manifest
        return manifests

    def _stage_archive(self, archive: Path) -> _Candidate:
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ModError(f"Archive exceeds {MAX_ARCHIVE_BYTES} bytes")
        staging_root = Path(tempfile.mkdtemp(prefix="amod-", dir=self.staging))
        try:
            with zipfile.ZipFile(archive) as source:
                infos = source.infolist()
                if len(infos) > MAX_ARCHIVE_FILES:
                    raise ModError(f"Archive contains more than {MAX_ARCHIVE_FILES} entries")
                total = 0
                seen: set[str] = set()
                for info in infos:
                    name = _safe_zip_name(info.filename)
                    if name in seen:
                        raise ModError(f"Archive contains duplicate entry: {name}")
                    seen.add(name)
                    if _is_symlink(info):
                        raise ModError(f"Archive contains symlink: {name}")
                    total += info.file_size
                    if total > MAX_UNPACKED_BYTES:
                        raise ModError(f"Archive expands beyond {MAX_UNPACKED_BYTES} bytes")
                    target = staging_root / name
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(info) as input_file, target.open("wb") as output_file:
                        shutil.copyfileobj(input_file, output_file, length=1024 * 1024)

            _validate_archive_layout(staging_root)
            manifest = _parse_manifest(_read_json(staging_root / "manifest.json"))
            character_metadata = _read_json(staging_root / "character.json")
            if (
                not isinstance(character_metadata, dict)
                or manifest.id != character_metadata.get("id")
                or manifest.display_name != character_metadata.get("display_name")
            ):
                raise ModError(
                    "manifest id/display_name must match character.json"
                )
            pack_dir = staging_root / manifest.id
            pack_dir.mkdir()
            for child in list(staging_root.iterdir()):
                if child != pack_dir:
                    child.replace(pack_dir / child.name)
            load_character(
                manifest.id,
                root=os.fspath(staging_root),
                source="mod",
                version=manifest.version,
            )
            return _Candidate(archive, manifest, pack_dir, staging_root)
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

    def _activate(self, candidate: _Candidate) -> None:
        destination = self.installed / candidate.manifest.id
        backup = self.installed / f".{candidate.manifest.id}.backup"
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.replace(backup)
        try:
            candidate.staged_dir.replace(destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if backup.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)


def _validate_archive_layout(root: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if len(relative.parts) == 1:
            if path.is_dir():
                if path.name not in _ALLOWED_ROOT_DIRS:
                    raise ModError(f"Unexpected archive directory: {path.name}")
            elif path.name not in _ALLOWED_ROOT_FILES:
                raise ModError(f"Unexpected archive file: {path.name}")
        elif relative.parts[0] not in _ALLOWED_ROOT_DIRS:
            raise ModError(f"Unexpected archive path: {relative.as_posix()}")


def _safe_zip_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ":" in normalized:
        raise ModError(f"Unsafe archive path: {name}")
    parts = [part for part in normalized.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ModError(f"Unsafe archive path: {name}")
    return "/".join(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _parse_manifest(raw: Any) -> ModManifest:
    if not isinstance(raw, dict):
        raise ModError("manifest.json must contain an object")
    unknown = set(raw) - _MANIFEST_KEYS
    if unknown:
        raise ModError(f"Unsupported manifest property: {next(iter(unknown))}")
    if raw.get("format") != _MOD_FORMAT or raw.get("schema_version") != 1:
        raise ModError("Unsupported mod format or schema version")
    mod_id = raw.get("id")
    version = raw.get("version")
    display_name = raw.get("display_name")
    if not isinstance(mod_id, str) or not _safe_mod_id(mod_id):
        raise ModError("manifest id is invalid")
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise ModError("manifest version must be semantic major.minor.patch")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ModError("manifest display_name is required")
    return ModManifest(mod_id, version, display_name.strip(), raw)


def _safe_mod_id(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", value)) and "/" not in value


def _version_key(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise ModError(f"Invalid semantic version: {version}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
