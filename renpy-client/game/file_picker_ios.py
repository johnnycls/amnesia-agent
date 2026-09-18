"""iOS UIDocumentPicker adapter.

The Objective-C bridge is supplied by ``native/ios/RenpyFilePicker.m``. The
bridge performs the document import/copy into shared ``mods/.staging`` and
invokes the delegate with that staging path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from api.client import invoke
from file_picker import FilePickerUnavailable, PickerResult

try:
    from pyobjus import autoclass, protocol
except ImportError:  # pragma: no cover - only imported on iOS
    autoclass = None  # type: ignore[assignment]

    def protocol(*_args: Any, **_kwargs: Any):
        def decorate(function: Any) -> Any:
            return function

        return decorate


class _Delegate:
    """Pyobjus delegate expected by RenpyFilePickerDelegate."""

    def __init__(self, callback: Any) -> None:
        self.callback = callback

    @protocol("RenpyFilePickerDelegate")
    def filePicker_didFinishWithPath_error_cancelled_(
        self,
        picker: Any,
        path: Any,
        error: Any,
        cancelled: Any,
    ) -> None:
        local_path = Path(path.UTF8String()) if path is not None else None
        message = error.UTF8String() if error is not None else ""
        invoke(
            self.callback,
            PickerResult(
                path=local_path,
                error=message,
                cancelled=bool(cancelled),
            ),
        )


class IOSPickerAdapter:
    def __init__(self) -> None:
        if autoclass is None:
            raise FilePickerUnavailable("Pyobjus is unavailable in this iOS build.")
        try:
            self.bridge = autoclass("RenpyFilePicker").alloc().init()
        except Exception as error:  # noqa: BLE001 — missing packaged ObjC bridge
            raise FilePickerUnavailable(
                "The iOS file picker bridge is not included in this build."
            ) from error
        self._delegate: _Delegate | None = None

    def pick_one(self, staging_dir: str, callback: Any) -> None:
        self._delegate = _Delegate(callback)
        try:
            self.bridge.openAmodPickerWithDelegate_temporaryDirectory_(
                self._delegate,
                os.fspath(staging_dir),
            )
        except Exception as error:  # noqa: BLE001 — UIKit/bridge failure
            self._delegate = None
            invoke(callback, PickerResult(error=f"Could not open iOS file picker: {error}"))
