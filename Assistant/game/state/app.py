"""Assistant application state: Loading → Config (if needed) → Character Select → Main."""

from __future__ import annotations

import threading
from typing import Any

from api.client import ApiError, Client, TurnHandle, invoke
from characters.loader import CharacterError, CharacterPack, load_all_characters
from process.lifecycle import ServerProcess

from state.config_gate import (
    format_config_required_status,
    is_provider_configured,
    provider_config_gaps,
)
from state.stage import apply_stage

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]


class AppState:
    """Single source of UI state for the Assistant Ren'Py client."""

    def __init__(self) -> None:
        self.client = Client()
        self.server = ServerProcess(self.client)

        self.page = "loading"
        self.status = ""
        self.error = ""
        self.busy = False
        self.starting = False
        self.ready = False

        self.characters: list[CharacterPack] = []
        self.character: CharacterPack | None = None
        self.current_bg = ""
        self.current_expression = ""
        self.bg_path = ""
        self.sprite_path = ""

        self.last_assistant_text = ""
        self.last_assistant_choices: list[str] = []
        self.turn_handle: TurnHandle | None = None
        self.input_text = ""

        self.settings_model = ""
        self.settings_api_key = ""
        self.settings_api_key_set = False
        self.provider_configured = False
        self.config_return_page = "character_select"

    # --- bootstrap / loading -------------------------------------------------

    def start_loading(self) -> None:
        if self.starting or self.ready:
            return
        self.starting = True
        self.page = "loading"
        self.status = "Starting local server..."
        self.error = ""
        self._refresh()

        def work() -> None:
            try:
                self.server.start()
                health = self.client.health(timeout=2.0)
                if health.get("status") != "ok":
                    raise ApiError(f"Unexpected health response: {health!r}")
                packs = load_all_characters()
                if len(packs) < 2:
                    raise CharacterError(
                        f"Expected at least two character packs, found {len(packs)}"
                    )
                config = self.client.request_json("GET", "/v1/config")
                invoke(self._loading_ok, packs, config)
            except (ApiError, CharacterError, OSError) as error:
                invoke(self._loading_failed, error)
            except Exception as error:  # noqa: BLE001
                invoke(self._loading_failed, error)

        threading.Thread(target=work, name="assistant-loading", daemon=True).start()

    def _loading_ok(self, packs: list[CharacterPack], config: dict[str, Any]) -> None:
        self.starting = False
        self.ready = True
        self.characters = packs
        self.error = ""
        self._apply_server_config(config, refresh=False)
        if self.provider_configured:
            self.page = "character_select"
            self.status = "Ready"
        else:
            self.config_return_page = "character_select"
            self.page = "config"
            gaps = provider_config_gaps(config)
            self.status = format_config_required_status(gaps)
        self._refresh()

    def _loading_failed(self, error: Exception) -> None:
        self.starting = False
        self.ready = False
        self.status = f"Server startup failed: {error}"
        self.error = str(error)
        self._refresh()

    # --- character select ----------------------------------------------------

    def select_character(self, character_id: str) -> None:
        if self.busy or not self.ready:
            return
        if not self.provider_configured:
            self._force_config("Set model and API key before selecting a character.")
            return
        pack = next((c for c in self.characters if c.id == character_id), None)
        if pack is None:
            self.status = f"Unknown character: {character_id}"
            self._refresh()
            return
        self.status = f"Loading {pack.display_name}..."
        self._refresh()

        def work() -> None:
            try:
                # Default workspace: omit workspace_path so server uses ~/.amnesia-agent.
                self.client.request_json("POST", "/v1/workspace/setup-or-repair")
                self.client.request_json(
                    "PUT",
                    "/v1/workspace/system-prompt",
                    {"content": pack.prompt},
                )
                invoke(self._character_ready, pack)
            except Exception as error:  # noqa: BLE001
                invoke(self._character_failed, error)

        threading.Thread(target=work, name="assistant-char-select", daemon=True).start()

    def _character_ready(self, pack: CharacterPack) -> None:
        self.character = pack
        self.current_bg = pack.default_bg
        self.current_expression = pack.default_expression
        self._sync_stage_paths()
        self.last_assistant_text = ""
        self.last_assistant_choices = []
        self.page = "main"
        self.status = f"Playing as {pack.display_name}"
        self._refresh()

    def _character_failed(self, error: Exception) -> None:
        self.status = f"Character setup failed: {error}"
        self._refresh()

    def go_character_select(self) -> None:
        if self.busy:
            self.status = "Cannot switch character while busy."
            self._refresh()
            return
        self.page = "character_select"
        self.status = "Select a character"
        self._refresh()

    def reset_default_workspace(self) -> None:
        """Confirm then hard-reset ~/.amnesia-agent and re-apply the current character."""
        if self.busy or not self.ready:
            return
        pack = self.character
        if pack is None:
            self.status = "Select a character before resetting the workspace."
            self._refresh()
            return
        message = (
            "Hard-reset the default workspace? This deletes the entire "
            "~/.amnesia-agent folder contents."
        )
        if renpy is not None and not renpy.confirm(message):
            return
        self.status = "Resetting workspace..."
        self._refresh()

        def work() -> None:
            try:
                # Default workspace: omit workspace_path.
                self.client.request_json("POST", "/v1/workspace/create-or-reset")
                self.client.request_json(
                    "PUT",
                    "/v1/workspace/system-prompt",
                    {"content": pack.prompt},
                )
                invoke(self._reset_ok, pack)
            except Exception as error:  # noqa: BLE001
                invoke(self._reset_failed, error)

        threading.Thread(target=work, name="assistant-reset-ws", daemon=True).start()

    def _reset_ok(self, pack: CharacterPack) -> None:
        self.character = pack
        self.current_bg = pack.default_bg
        self.current_expression = pack.default_expression
        self.last_assistant_text = ""
        self.last_assistant_choices = []
        self._sync_stage_paths()
        self.status = "Workspace reset"
        self.error = ""
        self._refresh()

    def _reset_failed(self, error: Exception) -> None:
        self.status = f"Workspace reset failed: {error}"
        self.error = str(error)
        self._refresh()

    # --- main / turn ---------------------------------------------------------

    def send(self, text: str) -> None:
        text = text.strip()
        if not text or not self.ready or self.busy or self.character is None:
            return
        if not self.provider_configured:
            self._force_config("Set model and API key before starting a turn.")
            return
        self.input_text = ""
        self._set_store("input_text", "")
        self.last_assistant_choices = []
        self.busy = True
        self._sync_stage_paths()
        self.status = "Thinking..."
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
        # Only signal the stream to stop; busy clears in _on_complete / _on_error
        # once the SSE thread finishes (socket close / cancelled loop exit).
        if self.turn_handle is None:
            return
        self.turn_handle.cancel()
        self.status = "Cancelling..."
        self._refresh()

    def _cancel_requested(self) -> bool:
        return self.turn_handle is not None and self.turn_handle.cancelled

    def _finish_cancelled(self) -> None:
        self.busy = False
        self.turn_handle = None
        self._sync_stage_paths()
        self.status = "Cancelled"
        self._refresh()

    def _on_event(self, event: dict[str, Any]) -> None:
        if self._cancel_requested():
            return
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
        if event_type == "delta":
            self.status = "Streaming..."
        elif event_type == "assistant":
            tool_calls = data.get("tool_calls") or []
            if isinstance(tool_calls, list) and tool_calls:
                self.status = "Running tool..."
            else:
                self._apply_assistant_stage(data)
        elif event_type == "tool_result":
            self.status = "Thinking..."
        elif event_type == "error":
            message = data.get("message", "Unknown error")
            self.last_assistant_text = f"Error: {message}"
            self.last_assistant_choices = []
            self.busy = False
            self._sync_stage_paths()
            self.status = "Request failed"
        elif event_type == "done":
            self.busy = False
            self.turn_handle = None
            self._sync_stage_paths()
            if not self.status.startswith("Warning"):
                self.status = "Ready"
        self._refresh()

    def _apply_assistant_stage(self, data: dict[str, Any]) -> None:
        pack = self.character
        if pack is None:
            return
        result = apply_stage(
            data,
            background_ids=set(pack.backgrounds),
            expression_ids=set(pack.expressions) - {"busy"},
            previous_bg=self.current_bg,
            previous_expression=self.current_expression,
        )
        self.last_assistant_text = result.message
        self.last_assistant_choices = result.choices
        if result.bg is not None:
            self.current_bg = result.bg
        if result.expression is not None:
            self.current_expression = result.expression
        self._sync_stage_paths()
        if result.warnings:
            self.status = "Warning: " + "; ".join(result.warnings)
        else:
            self.status = "Ready"

    def _on_error(self, error: Exception) -> None:
        if self._cancel_requested():
            self._finish_cancelled()
            return
        self.turn_handle = None
        self.busy = False
        self._sync_stage_paths()
        self.last_assistant_text = f"Error: {error}"
        self.last_assistant_choices = []
        self.status = "Request failed"
        self._refresh()

    def _on_complete(self) -> None:
        if self._cancel_requested():
            self._finish_cancelled()
            return
        self.busy = False
        self.turn_handle = None
        self._sync_stage_paths()
        if self.status not in ("Request failed",) and not self.status.startswith(
            "Warning"
        ):
            self.status = "Ready"
        self._refresh()

    # --- config --------------------------------------------------------------

    def go_config(self) -> None:
        if self.busy:
            self.status = "Cannot open config while busy."
            self._refresh()
            return
        if self.page in ("character_select", "main", "config"):
            self.config_return_page = (
                self.page if self.page != "config" else self.config_return_page
            )
        else:
            self.config_return_page = "character_select"
        self.page = "config"
        self.load_config_form()
        self._refresh()

    def leave_config(self) -> None:
        if not self.provider_configured:
            self.status = format_config_required_status(
                provider_config_gaps(
                    {
                        "model": self.settings_model,
                        "api_key_set": self.settings_api_key_set,
                    }
                )
            )
            self._refresh()
            return
        target = self.config_return_page or "character_select"
        if target == "main" and self.character is None:
            target = "character_select"
        self.page = target
        self.status = "Ready" if target != "main" else self.status
        if target == "character_select":
            self.status = "Select a character"
        self._refresh()

    def _force_config(self, reason: str) -> None:
        self.config_return_page = self.page if self.page != "config" else self.config_return_page
        self.page = "config"
        self.status = reason
        self.load_config_form()
        self._refresh()

    def load_config_form(self) -> None:
        self.status = "Loading settings..."
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json("GET", "/v1/config")
                invoke(self._apply_server_config, config)
            except Exception as error:  # noqa: BLE001
                invoke(self._config_failed, error)

        threading.Thread(target=work, name="assistant-cfg-load", daemon=True).start()

    def _apply_server_config(
        self, config: dict[str, Any], *, refresh: bool = True
    ) -> None:
        self.settings_model = str(config.get("model") or "")
        self.settings_api_key = ""
        self.settings_api_key_set = bool(config.get("api_key_set"))
        self.provider_configured = is_provider_configured(config)
        self._set_store("settings_model", self.settings_model)
        self._set_store("settings_api_key", self.settings_api_key)
        if refresh:
            if self.provider_configured:
                if self.status.startswith("Loading") or self.status.startswith(
                    "Configure required"
                ):
                    self.status = "Ready"
            else:
                self.status = format_config_required_status(provider_config_gaps(config))
            self._refresh()

    def save_config_form(self, model: str, api_key: str) -> None:
        if self.busy:
            self.status = "Cannot save config while the agent is busy."
            self._refresh()
            return
        model = (model or "").strip()
        api_key = api_key or ""
        if not model:
            self.status = "Model is required (no empty default)."
            self._refresh()
            return
        if not api_key.strip() and not self.settings_api_key_set:
            self.status = "API key is required on first run (cannot leave blank)."
            self._refresh()
            return
        payload: dict[str, Any] = {"model": model}
        if api_key.strip():
            payload["api_key"] = api_key.strip()
        self.status = "Saving settings..."
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json("PUT", "/v1/config", payload)
                invoke(self._config_saved, config)
            except Exception as error:  # noqa: BLE001
                invoke(self._config_failed, error)

        threading.Thread(target=work, name="assistant-cfg-save", daemon=True).start()

    def _config_saved(self, config: dict[str, Any]) -> None:
        self._apply_server_config(config, refresh=False)
        if not self.provider_configured:
            self.page = "config"
            self.status = format_config_required_status(provider_config_gaps(config))
            self._refresh()
            return
        self.status = "Settings saved"
        target = self.config_return_page or "character_select"
        if target == "main" and self.character is None:
            target = "character_select"
        self.page = target
        if target == "character_select":
            self.status = "Settings saved — select a character"
        self._refresh()

    def _config_failed(self, error: Exception) -> None:
        self.status = f"Config error: {error}"
        self.error = str(error)
        self._refresh()

    # --- quit ----------------------------------------------------------------

    def can_quit(self) -> bool:
        return not self.busy

    def quit_app(self) -> None:
        if self.busy:
            self.status = "Cannot quit while the agent is busy."
            self._refresh()
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

    def _sync_stage_paths(self) -> None:
        pack = self.character
        if pack is None:
            self.bg_path = ""
            self.sprite_path = ""
            return
        self.bg_path = pack.backgrounds.get(self.current_bg, "")
        # `busy` is UI-only while a turn is in flight; LLM stage ids stay elsewhere.
        if self.busy and "busy" in pack.expressions:
            self.sprite_path = pack.expressions["busy"]
        else:
            self.sprite_path = pack.expressions.get(self.current_expression, "")

    def _refresh(self) -> None:
        if renpy is not None:
            renpy.restart_interaction()

    def _set_store(self, name: str, value: Any) -> None:
        if renpy is not None:
            setattr(renpy.store, name, value)
