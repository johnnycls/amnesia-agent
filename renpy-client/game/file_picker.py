"""One-file .amod picker seam for desktop and mobile builds.

Adapters only stage one selected file. The mod-store transaction owns the
staging directory and clears it after every operation.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from api.client import invoke


class FilePickerUnavailable(RuntimeError):
    """The current packaged target has no native picker bridge."""


@dataclass(frozen=True)
class PickerResult:
    """Completion of one picker request."""

    path: Path | None = None
    cancelled: bool = False
    error: str = ""


PickerCallback = Callable[[PickerResult], None]


class PickerAdapter(Protocol):
    def pick_one(
        self,
        staging_dir: str | os.PathLike[str],
        callback: PickerCallback,
    ) -> None:
        """Stage one .amod selection and complete exactly once."""


def _stage_desktop_file(
    source: str | os.PathLike[str],
    staging_dir: str | os.PathLike[str],
) -> Path:
    """Copy a user-selected desktop file into caller-owned staging."""
    source_path = Path(source)
    if source_path.suffix.casefold() != ".amod":
        raise ValueError("Please select a .amod character archive.")
    if not source_path.is_file():
        raise OSError("The selected file is no longer available.")
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    fd, destination = tempfile.mkstemp(
        prefix="amod-import-",
        suffix=".amod",
        dir=staging,
    )
    os.close(fd)
    target = Path(destination)
    try:
        shutil.copyfile(source_path, target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


class DesktopPickerAdapter:
    """Use Ren'Py's bundled tinyfiledialogs wrapper on desktop targets."""

    def pick_one(
        self,
        staging_dir: str | os.PathLike[str],
        callback: PickerCallback,
    ) -> None:
        try:
            import renpy  # type: ignore[import-not-found]
        except ImportError:
            callback(PickerResult(error="The Ren'Py file picker is unavailable."))
            return

        tfd = getattr(renpy, "tfd", None)
        if tfd is None:
            callback(PickerResult(error="The desktop file picker is unavailable in this build."))
            return
        try:
            selected = tfd.openFileDialog(
                "Import character",
                None,
                ["*.amod"],
                "Amnesia character archives",
                False,
            )
        except Exception as error:  # noqa: BLE001 — native bridge failure
            callback(PickerResult(error=f"Could not open the file picker: {error}"))
            return
        if not selected:
            callback(PickerResult(cancelled=True))
            return
        if "|" in selected:
            callback(PickerResult(error="Select exactly one .amod file."))
            return
        try:
            staged = _stage_desktop_file(selected, staging_dir)
        except (OSError, ValueError) as error:
            callback(PickerResult(error=str(error)))
            return
        callback(PickerResult(path=staged))


class NativeBridgePickerAdapter:
    """Adapter for a bridge exposing one callback-based picker.

    The bridge receives the shared staging directory and must copy the selected
    document there before calling ``complete``. Completion is marshalled through
    Ren'Py's main-thread dispatcher before reaching the game callback.
    """

    def __init__(self, bridge: object) -> None:
        self.bridge = bridge

    def pick_one(
        self,
        staging_dir: str | os.PathLike[str],
        callback: PickerCallback,
    ) -> None:
        def complete(
            path: str | None,
            error: str | None = None,
            cancelled: bool = False,
        ) -> None:
            result = PickerResult(
                path=Path(path) if path else None,
                cancelled=cancelled,
                error=error or "",
            )
            invoke(callback, result)

        try:
            start = getattr(self.bridge, "openAmodPicker", None)
            if start is None:
                raise FilePickerUnavailable("The native file picker bridge is incomplete.")
            start(os.fspath(staging_dir), complete)
        except Exception as error:  # noqa: BLE001 — native bridge failure
            invoke(callback, PickerResult(error=str(error)))


class FilePicker:
    """Deep one-file picker module with replaceable platform adapter."""

    def __init__(self, adapter: PickerAdapter | None = None) -> None:
        self.adapter = adapter or self._default_adapter()

    @staticmethod
    def _default_adapter() -> PickerAdapter:
        try:
            import renpy  # type: ignore[import-not-found]
        except ImportError:
            return DesktopPickerAdapter()

        if getattr(renpy, "android", False):
            try:
                from file_picker_android import AndroidPickerAdapter

                return AndroidPickerAdapter()
            except (ImportError, FilePickerUnavailable) as error:
                return _UnavailableAdapter(str(error))
        if getattr(renpy, "ios", False):
            try:
                from file_picker_ios import IOSPickerAdapter

                return IOSPickerAdapter()
            except (ImportError, FilePickerUnavailable) as error:
                return _UnavailableAdapter(str(error))
        return DesktopPickerAdapter()

    def pick_one(
        self,
        staging_dir: str | os.PathLike[str],
        callback: PickerCallback,
    ) -> None:
        self.adapter.pick_one(staging_dir, callback)


class _UnavailableAdapter:
    def __init__(self, message: str) -> None:
        self.message = message or "The file picker is unavailable on this build."

    def pick_one(
        self,
        staging_dir: str | os.PathLike[str],
        callback: PickerCallback,
    ) -> None:
        callback(PickerResult(error=self.message))


def cleanup_staged_file(path: Path | None) -> None:
    """Best-effort compatibility helper for picker-owned paths."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
