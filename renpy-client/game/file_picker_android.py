"""Android Storage Access Framework adapter.

The Java bridge is supplied by ``native/android/FilePickerBridge.java`` and
must be included in the generated Android activity. It copies the selected
content URI into the shared ``mods/.staging`` directory before invoking this
adapter.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from api.client import invoke
from file_picker import FilePickerUnavailable, PickerResult

try:
    from jnius import PythonJavaClass, java_method
except ImportError:  # pragma: no cover - only imported on Android
    PythonJavaClass = object  # type: ignore[assignment,misc]

    def java_method(*_args: Any, **_kwargs: Any):
        def decorate(function: Any) -> Any:
            return function

        return decorate


class _Callback(PythonJavaClass):
    """Pyjnius callback object used by FilePickerBridge.Callback."""

    __javainterfaces__ = ["org.amnesia.assistant.FilePickerBridge$Callback"]
    __javacontext__ = "app"

    def __init__(self, callback: Any) -> None:
        self.callback = callback

    @java_method("(Ljava/lang/String;Ljava/lang/String;Z)V")
    def onComplete(self, path: str | None, error: str | None, cancelled: bool) -> None:
        invoke(
            self.callback,
            PickerResult(
                path=Path(path) if path else None,
                error=error or "",
                cancelled=bool(cancelled),
            ),
        )


class AndroidPickerAdapter:
    def __init__(self) -> None:
        try:
            from jnius import autoclass
        except ImportError as error:
            raise FilePickerUnavailable("Pyjnius is unavailable in this Android build.") from error
        try:
            self.activity = autoclass("org.renpy.android.PythonSDLActivity").mActivity
            self.bridge = autoclass("org.amnesia.assistant.FilePickerBridge")
        except Exception as error:  # noqa: BLE001 — missing packaged Java bridge
            raise FilePickerUnavailable(
                "The Android file picker bridge is not included in this build."
            ) from error

    def pick_one(self, staging_dir: str, callback: Any) -> None:
        native_callback = _Callback(callback)
        try:
            self.bridge.openAmodPicker(
                self.activity,
                os.fspath(staging_dir),
                native_callback,
            )
        except Exception as error:  # noqa: BLE001 — activity/bridge failure
            invoke(callback, PickerResult(error=f"Could not open Android file picker: {error}"))
