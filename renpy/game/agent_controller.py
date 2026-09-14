"""Ren'Py-facing state controller for chat, settings, and workspace screens."""

from __future__ import annotations

import threading
from typing import Any

from local_server_client import (
    LocalServerClient,
    LocalServerError,
    TurnHandle,
    dispatch,
)

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]


class AgentController:
    """Keep screen state local while the server remains the source of truth."""

    def __init__(self) -> None:
        self.client = LocalServerClient()
        self.starting = False
        self.started = False
        self.busy = False
        self.status = _localized("Server is not started.")
        self.messages: list[dict[str, Any]] = []
        self.streaming_text = ""
        self.turn_handle: TurnHandle | None = None

    def start_async(self) -> None:
        if self.starting or self.started:
            return
        self.starting = True
        self.status = _localized("Starting local server...")
        self._refresh()

        def work() -> None:
            try:
                self.client.start()
                config = self.client.request_json("GET", "/v1/config")
                dispatch(self._started, config)
            except Exception as error:
                dispatch(self._start_failed, error)

        threading.Thread(target=work, name="amnesia-agent-start", daemon=True).start()

    def _started(self, config: dict[str, Any]) -> None:
        self.starting = False
        self.started = True
        self.status = _localized("Ready")
        self._apply_config(config)
        self._refresh()

    def _start_failed(self, error: Exception) -> None:
        self.starting = False
        self.started = False
        self.status = _localized("Server startup failed: {error}", error=error)
        self._refresh()

    def send(self, text: str) -> None:
        text = text.strip()
        if not text or not self.started or self.busy:
            return
        self.messages.append({"role": "user", "text": text})
        _set_store("input_text", "")
        self.streaming_text = ""
        self.busy = True
        self.status = _localized("Thinking...")
        self._refresh()
        self.turn_handle = self.client.stream_turn(
            text,
            self._on_event,
            self._on_error,
            self._on_complete,
        )

    def choose(self, choice: str) -> None:
        self.send(choice)

    def cancel(self) -> None:
        if self.turn_handle is not None:
            self.turn_handle.cancel()
        self.turn_handle = None
        self.busy = False
        self.status = _localized("Cancelled")
        self._refresh()

    def _on_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
        if event_type == "delta":
            text = data.get("text", "")
            self.streaming_text += text if isinstance(text, str) else str(text)
            self.status = _localized("Streaming...")
        elif event_type == "assistant":
            tool_calls = data.get("tool_calls") or []
            if isinstance(tool_calls, list) and tool_calls:
                self.messages.append({"role": "tool_call", "data": data})
                self.status = _localized("Running tool...")
            else:
                self.streaming_text = ""
                self.messages.append(
                    {
                        "role": "assistant",
                        "text": data.get("answer", data.get("content", "")),
                        "choices": data.get("choices", []),
                        "structured": data.get("structured", False),
                    }
                )
        elif event_type == "tool_call":
            # Legacy wire type (pre-unify); keep for older servers.
            self.messages.append({"role": "tool_call", "data": data})
            self.status = _localized("Running tool...")
        elif event_type == "tool_result":
            self.messages.append({"role": "tool_result", "data": data})
            self.status = _localized("Thinking...")
        elif event_type == "error":
            self.messages.append(
                {"role": "error", "text": data.get("message", "Unknown error")}
            )
            self.busy = False
            self.status = _localized("Request failed")
        elif event_type == "done":
            self.busy = False
            self.turn_handle = None
            self.status = _localized("Ready")
        self._refresh()

    def _on_error(self, error: Exception) -> None:
        self.turn_handle = None
        if not isinstance(error, LocalServerError):
            error = LocalServerError(str(error))
        self.messages.append({"role": "error", "text": str(error)})
        self.busy = False
        self.status = _localized("Request failed")
        self._refresh()

    def _on_complete(self) -> None:
        self.busy = False
        self.turn_handle = None
        self.status = _localized("Ready")
        self._refresh()

    def load_workspace_async(self) -> None:
        if not self.started:
            return

        def work() -> None:
            try:
                prompt = self.client.request_json("GET", "/v1/workspace/system-prompt")
                memory = self.client.request_json("GET", "/v1/workspace/memory")
                history = self.client.request_json("GET", "/v1/workspace/history")
                dispatch(self._apply_workspace, prompt, memory, history)
            except Exception as error:
                dispatch(self._workspace_failed, error)

        threading.Thread(
            target=work, name="amnesia-agent-workspace", daemon=True
        ).start()

    def load_history_date_async(self, date: str) -> None:
        if not self.started:
            return

        def work() -> None:
            try:
                history = self.client.request_json(
                    "GET", "/v1/workspace/history/" + date
                )
                dispatch(self._apply_history, history)
            except Exception as error:
                dispatch(self._workspace_failed, error)

        threading.Thread(target=work, name="amnesia-agent-history", daemon=True).start()

    def _apply_history(self, history: dict[str, Any]) -> None:
        _set_store("history_selected_date", str(history.get("date", "")))
        _set_store("history_content", _json_text(history.get("messages", [])))
        self.status = _localized("History loaded")
        self._refresh()

    def reset_history(self) -> None:
        if not self.started:
            return

        def work() -> None:
            try:
                self.client.request_json("POST", "/v1/workspace/history/reset")
                dispatch(self._history_reset)
            except Exception as error:
                dispatch(self._workspace_failed, error)

        threading.Thread(
            target=work, name="amnesia-agent-history-reset", daemon=True
        ).start()

    def _history_reset(self) -> None:
        _set_store("history_dates", [])
        _set_store("history_content", "[]")
        self.status = _localized("History reset")
        self._refresh()

    def _apply_workspace(
        self,
        prompt: dict[str, Any],
        memory: dict[str, Any],
        history: dict[str, Any],
    ) -> None:
        _set_store("system_prompt_text", str(prompt.get("content", "")))
        _set_store("memory_text", str(memory.get("content", "")))
        _set_store("history_dates", history.get("dates", []))
        self.status = _localized("Workspace loaded")
        self._refresh()

    def _workspace_failed(self, error: Exception) -> None:
        self.status = _localized("Workspace error: {error}", error=error)
        self._refresh()

    def save_settings(self, values: dict[str, Any]) -> None:
        if not self.started or self.busy:
            return
        self.status = _localized("Saving settings...")
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json("PUT", "/v1/config", values)
                dispatch(self._settings_saved, config)
            except Exception as error:
                dispatch(self._settings_failed, error)

        threading.Thread(
            target=work, name="amnesia-agent-settings", daemon=True
        ).start()

    def _settings_saved(self, config: dict[str, Any]) -> None:
        self._apply_config(config)
        self.status = _localized("Settings saved; next turn uses the new session.")
        self._refresh()

    def _settings_failed(self, error: Exception) -> None:
        self.status = _localized("Settings error: {error}", error=error)
        self._refresh()

    def reset_settings(self) -> None:
        if not self.started or self.busy:
            return
        self.status = _localized("Resetting settings...")
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json("POST", "/v1/config/reset")
                dispatch(self._settings_saved, config)
            except Exception as error:
                dispatch(self._settings_failed, error)

        threading.Thread(
            target=work, name="amnesia-agent-settings-reset", daemon=True
        ).start()

    def save_system_prompt(self, content: str) -> None:
        self._save_content("/v1/workspace/system-prompt", content)

    def save_memory(self, content: str) -> None:
        self._save_content("/v1/workspace/memory", content)

    def _save_content(self, path: str, content: str) -> None:
        if not self.started:
            return
        self.status = _localized("Saving workspace...")
        self._refresh()

        def work() -> None:
            try:
                self.client.request_json("PUT", path, {"content": content})
                dispatch(self._workspace_saved)
            except Exception as error:
                dispatch(self._workspace_failed, error)

        threading.Thread(
            target=work, name="amnesia-agent-workspace-save", daemon=True
        ).start()

    def reset_system_prompt(self) -> None:
        self._reset_content("/v1/workspace/system-prompt/reset")

    def reset_memory(self) -> None:
        self._reset_content("/v1/workspace/memory/reset")

    def _reset_content(self, path: str) -> None:
        if not self.started:
            return

        def work() -> None:
            try:
                content = self.client.request_json("POST", path)
                dispatch(self._content_reset, path, content)
            except Exception as error:
                dispatch(self._workspace_failed, error)

        threading.Thread(
            target=work, name="amnesia-agent-workspace-reset", daemon=True
        ).start()

    def _content_reset(self, path: str, content: dict[str, Any]) -> None:
        name = "system_prompt_text" if "system-prompt" in path else "memory_text"
        _set_store(name, str(content.get("content", "")))
        self.status = _localized("Workspace reset")
        self._refresh()

    def _workspace_saved(self) -> None:
        self.status = _localized("Workspace saved")
        self._refresh()

    def _apply_config(self, config: dict[str, Any]) -> None:
        _set_store("settings_model", str(config.get("model", "")))
        _set_store("settings_api_key", "")
        _set_store("settings_base_url", str(config.get("base_url") or ""))
        _set_store(
            "settings_provider_params", _json_text(config.get("provider_params", {}))
        )
        _set_store("settings_timeout", str(config.get("command_timeout_seconds", 1800)))
        _set_store(
            "settings_output_limit", str(config.get("max_command_output_bytes", 262144))
        )
        _set_store(
            "settings_context_limit", str(config.get("max_context_message_chars", 1000))
        )

    def _refresh(self) -> None:
        if renpy is not None:
            renpy.restart_interaction()

    def stop(self) -> None:
        self.client.stop()
        self.started = False
        self.starting = False


def _localized(template: str, **values: Any) -> str:
    """Translate controller status text while retaining plain-Python testability."""
    if renpy is not None:
        translate_string = getattr(renpy, "translate_string", None)
        if callable(translate_string):
            template = translate_string(template)
    return template.format(**values)


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, indent=2)


def _set_store(name: str, value: Any) -> None:
    if renpy is not None:
        setattr(renpy.store, name, value)
