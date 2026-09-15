"""Daily JSONL history storage with role-only validation."""

import json
import os
import shutil
import stat
import tempfile
import threading
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, cast
from weakref import WeakValueDictionary

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import WorkspaceError
from amnesia_agent_kernel.workspace.paths import (
    HISTORY_DIRECTORY,
    HISTORY_FILENAME,
    history_path,
    utc_date_string,
    validate_date,
)


class _HistoryLockHolder:
    """Strong-ref target for a path's history lock (WeakValueDictionary value)."""

    __slots__ = ("__weakref__", "lock")

    def __init__(self) -> None:
        self.lock = threading.RLock()


class HistoryStore:
    """Thread-safe history operations for one workspace root."""

    _lock_registry_guard: ClassVar[Any] = threading.Lock()
    # Locks release when no HistoryStore (via Workspace) keeps a holder alive.
    _lock_registry: ClassVar[WeakValueDictionary[str, _HistoryLockHolder]] = WeakValueDictionary()

    @classmethod
    def _lock_holder_for_root(cls, root: Path) -> _HistoryLockHolder:
        key = os.path.normcase(str(root))
        with cls._lock_registry_guard:
            holder = cls._lock_registry.get(key)
            if holder is None:
                holder = _HistoryLockHolder()
                cls._lock_registry[key] = holder
            return holder

    def __init__(self, root: Path, clock: Any) -> None:
        self.root = root
        self._clock = clock
        # Keep a strong ref so the WeakValueDictionary entry stays while we use it.
        self._lock_holder = self._lock_holder_for_root(root)
        self._history_lock = self._lock_holder.lock

    def _today(self) -> str:
        try:
            return utc_date_string(self._clock())
        except WorkspaceError:
            raise
        except Exception as e:
            raise WorkspaceError(f"Cannot determine current UTC date: {e}") from e

    def _utc_timestamp(self) -> str:
        """Return an ISO-8601 UTC timestamp from the store clock (e.g. ...+00:00)."""
        try:
            now = self._clock()
        except Exception as e:
            raise WorkspaceError(f"Cannot determine current UTC time: {e}") from e
        if not isinstance(now, datetime):
            raise WorkspaceError("Cannot determine current UTC time: clock must return datetime")
        if now.tzinfo is None:
            current = now.replace(tzinfo=timezone.utc)
        else:
            current = now.astimezone(timezone.utc)
        return current.isoformat()

    def list_history(self) -> list[str]:
        """Return available daily history dates, newest first."""
        with self._history_lock:
            return self._list_history_unlocked()

    def _list_history_unlocked(self) -> list[str]:
        directory = self.root / HISTORY_DIRECTORY
        dates: list[str] = []
        try:
            try:
                directory_mode = directory.stat().st_mode
            except FileNotFoundError:
                return []
            if not stat.S_ISDIR(directory_mode):
                return []
            for path in directory.iterdir():
                match = HISTORY_FILENAME.fullmatch(path.name)
                if not match or not stat.S_ISREG(path.stat().st_mode):
                    continue
                try:
                    date = validate_date(match.group("date"))
                except WorkspaceError:
                    continue
                dates.append(date)
        except OSError as e:
            raise WorkspaceError(
                f"Cannot enumerate history directory {directory}: {e}",
                path=str(directory),
            ) from e
        return sorted(dates, reverse=True)

    @staticmethod
    def _validate_history_record(value: Any, number: int) -> AllMessageValues:
        if not isinstance(value, dict):
            raise ValueError(f"line {number} is not a JSON object")
        if "role" not in value:
            raise ValueError(f"line {number} is not a message")
        role = value["role"]
        if role not in ("system", "user", "assistant", "tool"):
            raise ValueError(f"line {number} has an invalid role")
        if (
            "content" in value
            and value["content"] is not None
            and not isinstance(value["content"], str)
        ):
            raise ValueError(f"line {number} has invalid content")
        if "timestamp" in value and not isinstance(value["timestamp"], str):
            raise ValueError(f"line {number} has an invalid timestamp")
        if role == "tool" and (
            not isinstance(value.get("tool_call_id"), str) or not value["tool_call_id"]
        ):
            raise ValueError(f"line {number} has an invalid tool call ID")
        return cast(AllMessageValues, value)

    def read_history(self, date: str | None = None) -> list[AllMessageValues]:
        with self._history_lock:
            available_dates = self._list_history_unlocked() if date is None else []
            selected_date = available_dates[0] if available_dates else date
            if selected_date is None:
                return []
            selected_date = validate_date(selected_date)
            path = history_path(self.root, selected_date)
            try:
                try:
                    mode = path.stat().st_mode
                except FileNotFoundError:
                    return []
                if not stat.S_ISREG(mode):
                    raise IsADirectoryError(path)
                lines = path.read_text(encoding="utf-8").splitlines()
                history: list[AllMessageValues] = []
                for number, line in enumerate(lines, start=1):
                    if not line.strip():
                        continue
                    history.append(self._validate_history_record(json.loads(line), number))
                return history
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as e:
                raise WorkspaceError(f"Cannot read history {path}: {e}", path=str(path)) from e

    @staticmethod
    def _serialize_history(messages: Sequence[dict[str, Any]]) -> str:
        try:
            validated = [
                HistoryStore._validate_history_record(message, number)
                for number, message in enumerate(messages, start=1)
            ]
            return "".join(json.dumps(message, allow_nan=False) + "\n" for message in validated)
        except (TypeError, ValueError, OverflowError) as e:
            raise WorkspaceError(f"Cannot serialize history: {e}") from e

    def _stamp_missing_timestamps(
        self, messages: Sequence[AllMessageValues]
    ) -> list[dict[str, Any]]:
        """Return copies with UTC timestamps for messages that lack one.

        Does not mutate caller list items. Messages that already have a
        ``timestamp`` key are left unchanged (validation still applies later).
        Works on plain ``dict[str, Any]`` copies so stamping does not go through
        ``AllMessageValues`` TypedDict key assignment.
        """
        stamped: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, dict) and "timestamp" not in message:
                copied: dict[str, Any] = dict(message)
                copied["timestamp"] = self._utc_timestamp()
                stamped.append(copied)
            else:
                # Already stamped (or non-dict): do not mutate the caller object.
                stamped.append(cast(dict[str, Any], message))
        return stamped

    def update_history(self, messages: Sequence[AllMessageValues], date: str | None = None) -> None:
        if isinstance(messages, (str, bytes, bytearray)) or not isinstance(messages, Sequence):
            raise WorkspaceError("History messages must be a sequence of message objects")
        selected_date = validate_date(date) if date is not None else self._today()
        path = history_path(self.root, selected_date)
        with self._history_lock:
            try:
                if not messages:
                    # Empty write deletes the daily file (no leftover empty jsonl).
                    path.unlink(missing_ok=True)
                    if path.parent.is_dir() and not any(path.parent.iterdir()):
                        path.parent.rmdir()
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
                content = self._serialize_history(self._stamp_missing_timestamps(messages))
                self._atomic_replace(path, content)
            except WorkspaceError as e:
                if e.path is None:
                    raise WorkspaceError(str(e), path=str(path)) from e
                raise
            except (OSError, TypeError, ValueError, OverflowError) as e:
                raise WorkspaceError(f"Cannot write history {path}: {e}", path=str(path)) from e

    @staticmethod
    def _atomic_replace(path: Path, content: str) -> None:
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def append_history(self, message: AllMessageValues) -> None:
        """Persist a stamped copy of ``message``; never mutate the caller's object."""
        path = history_path(self.root, self._today())
        if isinstance(message, dict):
            persisted: dict[str, Any] = dict(message)
            persisted["timestamp"] = self._utc_timestamp()
        else:
            persisted = cast(dict[str, Any], message)
        try:
            content = self._serialize_history([persisted])
        except WorkspaceError as e:
            raise WorkspaceError(str(e), path=str(path)) from e
        with self._history_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except (OSError, TypeError, ValueError, OverflowError) as e:
                raise WorkspaceError(f"Cannot append history {path}: {e}", path=str(path)) from e

    def reset_history(self) -> None:
        directory = self.root / HISTORY_DIRECTORY
        with self._history_lock:
            try:
                try:
                    directory_mode = directory.stat().st_mode
                except FileNotFoundError:
                    return
                if not stat.S_ISDIR(directory_mode):
                    raise WorkspaceError(
                        f"History path is not a directory: {directory}",
                        path=str(directory),
                    )
                shutil.rmtree(directory)
            except WorkspaceError:
                raise
            except OSError as e:
                raise WorkspaceError(
                    f"Cannot reset history directory {directory}: {e}",
                    path=str(directory),
                ) from e
