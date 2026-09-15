"""Ren'Py-facing application state and screen navigation helpers."""

from __future__ import annotations

import json
import threading
from typing import Any

from api.client import ApiError, Client, TurnHandle, invoke
from defaults.system_prompt import DEFAULT_SYSTEM_PROMPT
from home_config.store import (
    SUPPORTED_LANGUAGES,
    ConfigError,
    RenpyConfig,
    RenpyConfigStore,
)
from process.lifecycle import ServerProcess

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]

LANGUAGE_NAMES = {
    "english": "English",
    "schinese": "简体中文",
    "tchinese": "繁體中文",
    "japanese": "日本語",
    "korean": "한국어",
}


def localize(template: str, **values: Any) -> str:
    if renpy is not None:
        translate_string = getattr(renpy, "translate_string", None)
        if callable(translate_string):
            template = translate_string(template)
    return template.format(**values)


def format_history_messages(messages: Any) -> str:
    """Format history messages as ``role: msg time`` lines for the History UI."""
    if not isinstance(messages, list):
        return ""
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role", "")
        if not isinstance(role, str):
            role = str(role)
        content = message.get("content", "")
        if content is None:
            text = ""
        elif isinstance(content, str):
            text = content
        else:
            text = str(content)
        text = " ".join(text.split())
        timestamp = message.get("timestamp")
        time = timestamp if isinstance(timestamp, str) and timestamp else "—"
        lines.append(f"{role}: {text} {time}")
    return "\n".join(lines)


class AppState:
    """Single source of UI state: page, busy, workspace, last assistant, status."""

    def __init__(self) -> None:
        self.client = Client()
        self.server = ServerProcess(self.client)
        self.config_store = RenpyConfigStore()
        self.renpy_config: RenpyConfig | None = None

        self.page = "loading"
        self.status = ""
        self.error = ""
        self.busy = False
        self.starting = False
        self.ready = False

        self.workspace_path = ""
        self.pending_workspace_path = ""

        self.last_assistant_text = ""
        self.last_assistant_choices: list[str] = []
        self.streaming_text = ""
        self.turn_handle: TurnHandle | None = None

        self.system_prompt_text = ""
        self.memory_text = ""
        self.history_dates: list[str] = []
        self.history_selected_date = ""
        self.history_content = ""

        self.settings_model = ""
        self.settings_api_key = ""
        self.settings_base_url = ""
        self.settings_provider_params = "{}"
        self.settings_timeout = "1800"
        self.settings_output_limit = "262144"
        self.settings_context_limit = "1000"
        self.settings_language = "english"
        self.settings_api_key_set = False

        self.input_text = ""

    # --- bootstrap / loading -------------------------------------------------

    def start_loading(self) -> None:
        if self.starting or self.ready:
            return
        self.starting = True
        self.page = "loading"
        self.status = localize("Starting local server...")
        self.error = ""
        self._refresh()

        def work() -> None:
            try:
                self.server.start()
                health = self.client.health(timeout=2.0)
                if health.get("status") != "ok":
                    raise ApiError(f"Unexpected health response: {health!r}")
                config = self.config_store.load()
                invoke(self._loading_ok, config)
            except (ApiError, ConfigError, OSError) as error:
                invoke(self._loading_failed, error)
            except Exception as error:  # noqa: BLE001
                invoke(self._loading_failed, error)

        threading.Thread(target=work, name="amnesia-loading", daemon=True).start()

    def _loading_ok(self, config: RenpyConfig) -> None:
        self.starting = False
        self.ready = True
        self.renpy_config = config
        self.settings_language = config.language
        self._apply_language(config.language)
        self.status = localize("Ready")
        self.error = ""
        # Auto-enter Main when recent[0] exists and check passes.
        if config.recent_workspaces:
            top = config.recent_workspaces[0].path
            self._try_auto_open(top)
            return
        self.page = "workspace_select"
        self._refresh()

    def _try_auto_open(self, path: str) -> None:
        self._set_status("Opening workspace...")

        def work() -> None:
            try:
                check = self.client.request_json(
                    "GET",
                    "/v1/workspace/check",
                    query={"workspace_path": path},
                )
                if not check.get("ok"):
                    invoke(self._auto_open_fallback)
                    return
                self.client.request_json(
                    "POST",
                    "/v1/workspace/setup-or-repair",
                    {"workspace_path": path},
                )
                invoke(self._opened_workspace, path)
            except Exception:  # noqa: BLE001 — fall back to selector
                invoke(self._auto_open_fallback)

        threading.Thread(target=work, name="amnesia-auto-open", daemon=True).start()

    def _auto_open_fallback(self) -> None:
        self.page = "workspace_select"
        self._set_status("Could not open recent workspace")

    def _loading_failed(self, error: Exception) -> None:
        self.starting = False
        self.ready = False
        self.status = localize("Server startup failed: {error}", error=error)
        self.error = str(error)
        self._refresh()

    # --- workspace select ----------------------------------------------------

    def recent_workspaces(self) -> list[dict[str, str]]:
        if self.renpy_config is None:
            return []
        return [
            {"path": e.path, "last_opened_at": e.last_opened_at}
            for e in self.renpy_config.recent_workspaces
        ]

    def delete_recent(self, path: str) -> None:
        try:
            self.renpy_config = self.config_store.remove_recent(path)
            self.status = localize("Removed from recent workspaces")
        except ConfigError as error:
            self.status = localize("Config error: {error}", error=error)
        self._refresh()

    @staticmethod
    def _ask_directory() -> str:
        """Native OS folder picker. Returns "" when cancelled."""
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            try:
                root.attributes("-topmost", True)
            except tk.TclError:
                pass
            selected = filedialog.askdirectory()
        finally:
            root.destroy()
        if not selected:
            return ""
        return str(selected).strip()

    def pick_import_workspace(self) -> None:
        """OS folder picker → open_workspace. Cancel is a no-op."""
        if self.busy:
            return

        def work() -> None:
            path = self._ask_directory()
            if not path:
                return
            invoke(self.open_workspace, path)

        threading.Thread(target=work, name="amnesia-pick-import", daemon=True).start()

    def pick_create_workspace(self) -> None:
        """OS folder picker → Confirm → create_workspace (empty-only create)."""
        if self.busy:
            return

        def work() -> None:
            path = self._ask_directory()
            if not path:
                return
            invoke(self._confirm_create_workspace, path)

        threading.Thread(target=work, name="amnesia-pick-create", daemon=True).start()

    def _confirm_create_workspace(self, path: str) -> None:
        """Confirm empty-only create; server refuses non-empty folders."""
        message = localize(
            "Create a workspace here? The folder must be empty (or new). "
            "Prompt and memory will be initialized empty."
        )
        if renpy is not None and not renpy.confirm(message):
            return
        self.create_workspace(path)

    def open_workspace(self, path: str) -> None:
        path = path.strip()
        if not path or self.busy:
            return
        self.status = localize("Opening workspace...")
        self._refresh()

        def work() -> None:
            try:
                check = self.client.request_json(
                    "GET",
                    "/v1/workspace/check",
                    query={"workspace_path": path},
                )
                if check.get("ok"):
                    self.client.request_json(
                        "POST",
                        "/v1/workspace/setup-or-repair",
                        {"workspace_path": path},
                    )
                    invoke(self._opened_workspace, path)
                else:
                    invoke(self._need_workspace_choice, path)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-open-ws", daemon=True).start()

    def _need_workspace_choice(self, path: str) -> None:
        self.pending_workspace_path = path
        self.page = "workspace_invalid"
        self.status = localize("Workspace is not valid")
        self._refresh()

    def resolve_workspace_choice(self, action: str) -> None:
        path = self.pending_workspace_path
        if not path or action not in ("setup_or_repair", "create_or_reset"):
            return
        self.status = localize("Preparing workspace...")
        self._refresh()
        endpoint = (
            "/v1/workspace/setup-or-repair"
            if action == "setup_or_repair"
            else "/v1/workspace/create-or-reset"
        )

        def work() -> None:
            try:
                self.client.request_json("POST", endpoint, {"workspace_path": path})
                invoke(self._opened_workspace, path)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-resolve-ws", daemon=True).start()

    def create_workspace(self, path: str) -> None:
        path = path.strip()
        if not path or self.busy:
            return
        self.status = localize("Creating workspace...")
        self._refresh()

        def work() -> None:
            try:
                self.client.request_json(
                    "POST",
                    "/v1/workspace/create",
                    {"workspace_path": path},
                )
                invoke(self._opened_workspace, path)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-create-ws", daemon=True).start()

    def _opened_workspace(self, path: str) -> None:
        try:
            self.renpy_config = self.config_store.bump_recent(path)
        except ConfigError as error:
            self.status = localize("Config error: {error}", error=error)
            self.page = "workspace_select"
            self._refresh()
            return
        self.workspace_path = path
        self.pending_workspace_path = ""
        self.last_assistant_text = ""
        self.last_assistant_choices = []
        self.streaming_text = ""
        self.page = "main"
        self.status = localize("Workspace loaded")
        self._refresh()

    def _workspace_failed(self, error: Exception) -> None:
        self.status = localize("Workspace error: {error}", error=error)
        self._refresh()

    def go_workspace_select(self) -> None:
        # Allow leave while busy; the turn keeps running in the background.
        self.page = "workspace_select"
        self._refresh()

    # --- main / turn ---------------------------------------------------------

    def send(self, text: str) -> None:
        text = text.strip()
        if not text or not self.ready or self.busy or not self.workspace_path:
            return
        self.input_text = ""
        self._set_store("input_text", "")
        self.streaming_text = ""
        self.last_assistant_choices = []
        self.busy = True
        self.status = localize("Thinking...")
        self._refresh()
        self.turn_handle = self.client.stream_turn(
            text,
            self.workspace_path,
            self._on_event,
            self._on_error,
            self._on_complete,
        )

    def choose(self, choice: str) -> None:
        self.send(choice)

    def cancel(self) -> None:
        # Only signal the stream to stop; busy clears in _on_complete / _on_error
        # once the SSE thread finishes (socket close / cancelled loop exit).
        if self.turn_handle is None:
            return
        self.turn_handle.cancel()
        self.status = localize("Cancelling...")
        self._refresh()

    def _cancel_requested(self) -> bool:
        return self.turn_handle is not None and self.turn_handle.cancelled

    def _finish_cancelled(self) -> None:
        self.busy = False
        self.turn_handle = None
        self.status = localize("Cancelled")
        self._refresh()

    def _on_event(self, event: dict[str, Any]) -> None:
        # After cancel, ignore late delta/assistant UI updates; terminal
        # done/error/complete still clear busy via _on_complete / _on_error.
        if self._cancel_requested():
            return
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
        if event_type == "delta":
            text = data.get("text", "")
            self.streaming_text += text if isinstance(text, str) else str(text)
            self.status = localize("Streaming...")
        elif event_type == "assistant":
            tool_calls = data.get("tool_calls") or []
            if isinstance(tool_calls, list) and tool_calls:
                self.status = localize("Running tool...")
            else:
                answer = data.get("answer", data.get("content", ""))
                choices = data.get("choices") or []
                self.streaming_text = ""
                self.last_assistant_text = (
                    answer if isinstance(answer, str) else str(answer)
                )
                if isinstance(choices, list):
                    self.last_assistant_choices = [
                        c for c in choices if isinstance(c, str)
                    ]
                else:
                    self.last_assistant_choices = []
        elif event_type == "tool_result":
            self.status = localize("Thinking...")
        elif event_type == "error":
            message = data.get("message", "Unknown error")
            self.last_assistant_text = localize("Error: {error}", error=message)
            self.last_assistant_choices = []
            self.busy = False
            self.status = localize("Request failed")
        elif event_type == "done":
            self.busy = False
            self.turn_handle = None
            self.status = localize("Ready")
        self._refresh()

    def _on_error(self, error: Exception) -> None:
        # Closing the socket on cancel often raises; treat as cancelled completion.
        if self._cancel_requested():
            self._finish_cancelled()
            return
        self.turn_handle = None
        self.busy = False
        self.last_assistant_text = localize("Error: {error}", error=error)
        self.last_assistant_choices = []
        self.status = localize("Request failed")
        self._refresh()

    def _on_complete(self) -> None:
        if self._cancel_requested():
            self._finish_cancelled()
            return
        self.busy = False
        self.turn_handle = None
        if self.status != localize("Request failed"):
            self.status = localize("Ready")
        self._refresh()

    # --- workspace settings --------------------------------------------------

    def go_workspace_settings(self) -> None:
        self.page = "workspace_settings"
        self.load_workspace_files()
        self._refresh()

    def load_workspace_files(self) -> None:
        if not self.workspace_path:
            return
        self._set_status("Loading workspace...")

        def work() -> None:
            try:
                prompt = self.client.request_json(
                    "GET",
                    "/v1/workspace/system-prompt",
                    query={"workspace_path": self.workspace_path},
                )
                memory = self.client.request_json(
                    "GET",
                    "/v1/workspace/memory",
                    query={"workspace_path": self.workspace_path},
                )
                invoke(
                    self._apply_workspace_files,
                    str(prompt.get("content", "")),
                    str(memory.get("content", "")),
                )
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-ws-files", daemon=True).start()

    def _apply_workspace_files(self, prompt: str, memory: str) -> None:
        self.system_prompt_text = prompt
        self.memory_text = memory
        self._set_store("system_prompt_text", prompt)
        self._set_store("memory_text", memory)
        self.status = localize("Workspace loaded")
        self._refresh()

    def save_system_prompt(self, content: str) -> None:
        self._put_workspace_file(
            "/v1/workspace/system-prompt", content, "system_prompt_text"
        )

    def save_memory(self, content: str) -> None:
        self._put_workspace_file("/v1/workspace/memory", content, "memory_text")

    def reset_system_prompt(self) -> None:
        """Write the packaged Ren'Py default string (not a server soft-reset)."""
        self.save_system_prompt(DEFAULT_SYSTEM_PROMPT)

    def clear_memory(self) -> None:
        """Empty memory.md via PUT (not a kernel soft-reset)."""
        self._put_workspace_file("/v1/workspace/memory", "", "memory_text")

    def _put_workspace_file(self, path: str, content: str, store_name: str) -> None:
        if not self.workspace_path:
            return
        if self.busy:
            self._set_status("Cannot save workspace while the agent is busy.")
            return
        self._set_status("Saving workspace...")

        def work() -> None:
            try:
                self.client.request_json(
                    "PUT",
                    path,
                    {"content": content, "workspace_path": self.workspace_path},
                )
                invoke(self._workspace_saved, store_name, content)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-ws-save", daemon=True).start()

    def _workspace_saved(self, store_name: str, content: str) -> None:
        setattr(self, store_name, content)
        self._set_store(store_name, content)
        self.status = localize("Workspace saved")
        self._refresh()

    # --- history -------------------------------------------------------------

    def go_history(self) -> None:
        self.page = "history"
        self.load_history_dates()
        self._refresh()

    def load_history_dates(self) -> None:
        if not self.workspace_path:
            return
        self._set_status("Loading history...")

        def work() -> None:
            try:
                history = self.client.request_json(
                    "GET",
                    "/v1/workspace/history",
                    query={"workspace_path": self.workspace_path},
                )
                dates = history.get("dates", [])
                if not isinstance(dates, list):
                    dates = []
                invoke(self._apply_history_dates, [str(d) for d in dates])
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-hist-dates", daemon=True).start()

    def _apply_history_dates(self, dates: list[str]) -> None:
        self.history_dates = dates
        self._set_store("history_dates", dates)
        self.status = localize("History loaded")
        self._refresh()

    def load_history_date(self, date: str) -> None:
        if not self.workspace_path:
            return
        self._set_status("Loading history...")

        def work() -> None:
            try:
                history = self.client.request_json(
                    "GET",
                    f"/v1/workspace/history/{date}",
                    query={"workspace_path": self.workspace_path},
                )
                invoke(self._apply_history_day, history)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-hist-day", daemon=True).start()

    def _apply_history_day(self, history: dict[str, Any]) -> None:
        self.history_selected_date = str(history.get("date", ""))
        content = format_history_messages(history.get("messages", []))
        self.history_content = content
        self._set_store("history_selected_date", self.history_selected_date)
        self._set_store("history_content", content)
        self.status = localize("History loaded")
        self._refresh()

    def delete_history_day(self) -> None:
        """Delete the selected day's JSONL via PUT empty messages (server unlinks file)."""
        if not self.workspace_path or not self.history_selected_date:
            return
        if self.busy:
            self._set_status("Cannot clear history while the agent is busy.")
            return
        selected = self.history_selected_date
        self._set_status("Deleting history day...")

        def work() -> None:
            try:
                self.client.request_json(
                    "PUT",
                    "/v1/workspace/history",
                    {
                        "messages": [],
                        "date": selected,
                        "workspace_path": self.workspace_path,
                    },
                )
                invoke(self._history_day_deleted, selected)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-hist-del-day", daemon=True).start()

    def _history_day_deleted(self, deleted_date: str) -> None:
        self.history_dates = [d for d in self.history_dates if d != deleted_date]
        self.history_selected_date = ""
        self.history_content = ""
        self._set_store("history_dates", self.history_dates)
        self._set_store("history_selected_date", "")
        self._set_store("history_content", "")
        self.status = localize("History day deleted")
        self._refresh()
        self.load_history_dates()

    def clear_history(self) -> None:
        if not self.workspace_path:
            return
        if self.busy:
            self._set_status("Cannot clear history while the agent is busy.")
            return
        self._set_status("Clearing history...")

        def work() -> None:
            try:
                self.client.request_json(
                    "POST",
                    "/v1/workspace/history/reset",
                    {"workspace_path": self.workspace_path},
                )
                invoke(self._history_cleared)
            except Exception as error:  # noqa: BLE001
                invoke(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-hist-reset", daemon=True).start()

    def _history_cleared(self) -> None:
        self.history_dates = []
        self.history_selected_date = ""
        self.history_content = ""
        self._set_store("history_dates", [])
        self._set_store("history_selected_date", "")
        self._set_store("history_content", "")
        self.status = localize("History reset")
        self._refresh()

    # --- config --------------------------------------------------------------

    def go_config(self) -> None:
        self.page = "config"
        self.load_config_form()
        self._refresh()

    def load_config_form(self) -> None:
        if self.renpy_config is not None:
            self.settings_language = self.renpy_config.language
            self._set_store("settings_language", self.settings_language)
        self._set_status("Loading settings...")

        def work() -> None:
            try:
                config = self.client.request_json("GET", "/v1/config")
                invoke(self._apply_server_config, config)
            except Exception as error:  # noqa: BLE001
                invoke(self._settings_failed, error)

        threading.Thread(target=work, name="amnesia-cfg-load", daemon=True).start()

    def _apply_server_config(self, config: dict[str, Any]) -> None:
        self.settings_model = str(config.get("model", ""))
        self.settings_api_key = ""
        self.settings_api_key_set = bool(config.get("api_key_set"))
        self.settings_base_url = str(config.get("base_url") or "")
        self.settings_provider_params = json.dumps(
            config.get("provider_params", {}), indent=2
        )
        self.settings_timeout = str(config.get("command_timeout_seconds", 1800))
        self.settings_output_limit = str(config.get("max_command_output_bytes", 262144))
        self.settings_context_limit = str(config.get("max_context_message_chars", 1000))
        for name in (
            "settings_model",
            "settings_api_key",
            "settings_base_url",
            "settings_provider_params",
            "settings_timeout",
            "settings_output_limit",
            "settings_context_limit",
        ):
            self._set_store(name, getattr(self, name))
        self.status = localize("Ready")
        self._refresh()

    def save_config_form(
        self,
        language: str,
        model: str,
        api_key: str,
        base_url: str,
        provider_params_text: str,
        timeout: str,
        output_limit: str,
        context_limit: str,
    ) -> None:
        if self.busy:
            self._set_status("Cannot save config while the agent is busy.")
            return
        try:
            provider_params = json.loads(provider_params_text or "{}")
            if not isinstance(provider_params, dict):
                raise ValueError("Provider params must be a JSON object")
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError(f"Unsupported language: {language}")
            server_payload: dict[str, Any] = {
                "model": model,
                "base_url": base_url,
                "provider_params": provider_params,
                "command_timeout_seconds": float(timeout),
                "max_command_output_bytes": int(output_limit),
                "max_context_message_chars": int(context_limit),
            }
            if api_key.strip():
                server_payload["api_key"] = api_key
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.status = localize("Invalid settings: {error}", error=error)
            self._refresh()
            return

        self.status = localize("Saving settings...")
        self._refresh()

        def work() -> None:
            try:
                # Ren'Py store first (local, fail loud).
                updated = self.config_store.set_language(language)
                # local_server fields.
                config = self.client.request_json("PUT", "/v1/config", server_payload)
                invoke(self._config_saved, updated, config)
            except Exception as error:  # noqa: BLE001
                invoke(self._settings_failed, error)

        threading.Thread(target=work, name="amnesia-cfg-save", daemon=True).start()

    def _config_saved(
        self, renpy_config: RenpyConfig, server_config: dict[str, Any]
    ) -> None:
        self.renpy_config = renpy_config
        self.settings_language = renpy_config.language
        self._apply_language(renpy_config.language)
        self._apply_server_config(server_config)
        self.status = localize("Settings saved; next turn uses the new session.")
        self._refresh()

    def reset_local_server_config(self) -> None:
        if self.busy:
            self._set_status("Cannot reset config while the agent is busy.")
            return
        self.status = localize("Resetting settings...")
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json("POST", "/v1/config/reset")
                invoke(self._server_config_reset, config)
            except Exception as error:  # noqa: BLE001
                invoke(self._settings_failed, error)

        threading.Thread(target=work, name="amnesia-cfg-reset-ls", daemon=True).start()

    def _server_config_reset(self, config: dict[str, Any]) -> None:
        self._apply_server_config(config)
        self.status = localize("Local server settings reset")
        self._refresh()

    def clear_api_key(self) -> None:
        """Explicitly clear the stored API key (blank field still means leave unchanged)."""
        if self.busy:
            self._set_status("Cannot clear API key while the agent is busy.")
            return
        self.status = localize("Clearing API key...")
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json(
                    "PUT", "/v1/config", {"api_key_clear": True}
                )
                invoke(self._api_key_cleared, config)
            except Exception as error:  # noqa: BLE001
                invoke(self._settings_failed, error)

        threading.Thread(target=work, name="amnesia-cfg-clear-key", daemon=True).start()

    def _api_key_cleared(self, config: dict[str, Any]) -> None:
        self._apply_server_config(config)
        self.status = localize("API key cleared")
        self._refresh()

    def reset_renpy_config(self) -> None:
        """Reset Ren'Py home JSON to defaults (language=english, recent=[])."""
        try:
            self.renpy_config = self.config_store.reset()
            self.settings_language = self.renpy_config.language
            self._set_store("settings_language", self.settings_language)
            self._apply_language(self.settings_language)
            self.status = localize("Ren'Py settings reset")
        except ConfigError as error:
            self.status = localize("Config error: {error}", error=error)
        self._refresh()

    def _settings_failed(self, error: Exception) -> None:
        self.status = localize("Settings error: {error}", error=error)
        self._refresh()

    def set_language_immediate(self, language: str) -> None:
        if language not in SUPPORTED_LANGUAGES:
            return
        try:
            self.renpy_config = self.config_store.set_language(language)
            self.settings_language = language
            self._set_store("settings_language", language)
            self._apply_language(language)
        except ConfigError as error:
            self.status = localize("Config error: {error}", error=error)
        self._refresh()

    def _apply_language(self, language: str) -> None:
        if renpy is None:
            return
        renpy.change_language(None if language == "english" else language)

    def language_display_name(self) -> str:
        return LANGUAGE_NAMES.get(self.settings_language, "English")

    # --- navigation / quit ---------------------------------------------------

    def go_main(self) -> None:
        self.page = "main"
        self._refresh()

    def can_quit(self) -> bool:
        return not self.busy

    def quit_app(self) -> None:
        if self.busy:
            self._set_status("Cannot quit while the agent is busy.")
            return
        self.server.stop()
        self.ready = False
        if renpy is not None:
            renpy.quit()

    def stop(self) -> None:
        if self.turn_handle is not None:
            self.turn_handle.cancel()
        self.server.stop()

    # --- helpers -------------------------------------------------------------

    def _set_status(self, template: str, **values: Any) -> None:
        self.status = localize(template, **values)
        self._refresh()

    def _refresh(self) -> None:
        if renpy is not None:
            renpy.restart_interaction()

    def _set_store(self, name: str, value: Any) -> None:
        if renpy is not None:
            setattr(renpy.store, name, value)
