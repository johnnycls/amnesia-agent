"""Assistant application state: Loading → Config / Character Select → Main (locked)."""

from __future__ import annotations

import json
import threading
from typing import Any

from api.client import ApiError, Client, TurnHandle, TurnTimeoutError, invoke
from characters.loader import CharacterError, CharacterPack, load_all_characters
from home_config.store import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    AssistantConfig,
    AssistantConfigStore,
    ConfigError,
)
from process.lifecycle import ServerProcess

from state.config_gate import (
    format_config_required_status,
    is_boot_ready,
    is_character_selected,
    is_provider_configured,
    next_setup_page,
    provider_config_gaps,
)
from state.stage import apply_stage

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


class AppState:
    """Single source of UI state for the Assistant Ren'Py client."""

    def __init__(self) -> None:
        self.client = Client()
        self.server = ServerProcess(self.client)
        self.config_store = AssistantConfigStore()
        self.assistant_config: AssistantConfig | None = None

        self.page = "loading"
        self.status = ""
        self.error = ""
        self.loading_recovery = ""
        self.recovery_busy = False
        self.operation: str | None = None
        self.operation_id = 0
        self.spinner_index = 0
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
        self.turn_id = 0
        self.active_turn_id: int | None = None
        self.input_text = ""

        self.settings_model = ""
        self.settings_api_key = ""
        self.settings_base_url = ""
        self.settings_provider_params = "{}"
        self.settings_language = DEFAULT_LANGUAGE
        self.settings_api_key_set = False
        self.provider_configured = False

    # --- bootstrap / loading -------------------------------------------------

    def _begin_operation(self, operation: str) -> int:
        if self.operation is not None:
            raise RuntimeError(f"Operation already active: {self.operation}")
        self.operation_id += 1
        self.operation = operation
        self.spinner_index = 0
        self._refresh()
        return self.operation_id

    def _operation_is_current(self, operation_id: int) -> bool:
        return self.operation is not None and self.operation_id == operation_id

    def _end_operation(self, operation_id: int) -> None:
        if self._operation_is_current(operation_id):
            self.operation = None
            self._refresh()

    def spinner_frame(self) -> str:
        return ("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self.spinner_index % 10])

    def advance_spinner(self) -> None:
        if self.operation is not None:
            self.spinner_index = (self.spinner_index + 1) % 10
            self._refresh()

    def start_loading(self) -> None:
        if self.starting or self.ready or self.operation is not None:
            return
        operation_id = self._begin_operation("starting")
        self.starting = True
        self.page = "loading"
        self.status = "Starting local server..."
        self.error = ""
        self.loading_recovery = ""
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
                try:
                    assistant_config = self.config_store.load()
                except ConfigError as error:
                    invoke(self._loading_failed, error, "assistant_config", operation_id)
                    return
                try:
                    config = self.client.request_json("GET", "/v1/config")
                except ApiError as error:
                    invoke(self._loading_failed, error, "server_config", operation_id)
                    return
                invoke(self._loading_ok, packs, config, assistant_config, operation_id)
            except (ApiError, CharacterError, ConfigError, OSError) as error:
                invoke(self._loading_failed, error, "", operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._loading_failed, error, "", operation_id)

        threading.Thread(target=work, name="assistant-loading", daemon=True).start()

    def _loading_ok(
        self,
        packs: list[CharacterPack],
        config: dict[str, Any],
        assistant_config: AssistantConfig,
        operation_id: int,
    ) -> None:
        if not self._operation_is_current(operation_id):
            return
        self.starting = False
        self.recovery_busy = False
        self.loading_recovery = ""
        self._end_operation(operation_id)
        self.ready = True
        self.characters = packs
        self.assistant_config = assistant_config
        self.settings_language = assistant_config.language
        self._apply_language(assistant_config.language)
        self.error = ""
        self._apply_server_config(config, refresh=False)
        self._route_from_readiness(status_when_main="Ready")

    def _loading_failed(
        self, error: Exception, recovery: str, operation_id: int
    ) -> None:
        if not self._operation_is_current(operation_id):
            return
        self.starting = False
        self.recovery_busy = False
        self._end_operation(operation_id)
        self.ready = False
        self.loading_recovery = recovery
        self.status = f"Server startup failed: {error}"
        self.error = str(error)
        self._refresh()

    def reset_server_config(self) -> None:
        """Reset corrupt local-server settings, then resume normal startup."""
        if self.starting or self.operation is not None or self.ready:
            return
        if renpy is not None and not renpy.confirm(
            "Reset server settings? This removes the stored API key and provider settings."
        ):
            return
        operation_id = self._begin_operation("recovering_server_config")
        self.recovery_busy = True
        self.status = "Resetting server settings..."
        self.error = ""
        self._refresh()

        def work() -> None:
            try:
                self.client.request_json("POST", "/v1/config/reset")
                invoke(self._recovery_succeeded, operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._recovery_failed, error, operation_id)

        threading.Thread(target=work, name="assistant-reset-server-config", daemon=True).start()

    def reset_assistant_config(self) -> None:
        """Reset Assistant preferences, then resume normal startup."""
        if self.starting or self.operation is not None or self.ready:
            return
        if renpy is not None and not renpy.confirm(
            "Reset Assistant preferences? This clears the selected character and language."
        ):
            return
        operation_id = self._begin_operation("recovering_assistant_config")
        self.recovery_busy = True
        self.status = "Resetting Assistant preferences..."
        self.error = ""
        self._refresh()

        def work() -> None:
            try:
                self.config_store.reset()
                invoke(self._recovery_succeeded, operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._recovery_failed, error, operation_id)

        threading.Thread(target=work, name="assistant-reset-preferences", daemon=True).start()

    def _recovery_succeeded(self, operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self.recovery_busy = False
        self.error = ""
        self.status = "Settings reset. Loading..."
        self._end_operation(operation_id)
        self.start_loading()

    def _recovery_failed(self, error: Exception, operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self.recovery_busy = False
        self._end_operation(operation_id)
        self.status = f"Settings reset failed: {error}"
        self.error = str(error)
        self._refresh()

    # --- readiness routing ---------------------------------------------------

    def _available_character_ids(self) -> set[str]:
        return {c.id for c in self.characters}

    def _selected_character_id(self) -> str:
        if self.assistant_config is None:
            return ""
        return self.assistant_config.selected_character_id

    def _character_ok(self) -> bool:
        return is_character_selected(
            self._selected_character_id(), self._available_character_ids()
        )

    def _resolve_selected_pack(self) -> CharacterPack | None:
        selected = self._selected_character_id()
        if not selected:
            return None
        return next((c for c in self.characters if c.id == selected), None)

    def _route_from_readiness(self, *, status_when_main: str) -> None:
        """Send user to Main (apply character) or the next setup page."""
        provider_ok = self.provider_configured
        character_ok = self._character_ok()
        if is_boot_ready(provider_ok=provider_ok, character_ok=character_ok):
            pack = self._resolve_selected_pack()
            if pack is None:
                # Defensive: character_ok True implies pack exists.
                self.page = "character_select"
                self.status = "Select a character"
                self._refresh()
                return
            # Already applied this pack (e.g. Back from Config while on Main).
            if self.character is not None and self.character.id == pack.id:
                self.page = "main"
                self.status = status_when_main or f"Playing as {pack.display_name}"
                self._sync_stage_paths()
                self._refresh()
                return
            self.status = f"Loading {pack.display_name}..."
            self._refresh()
            self._begin_apply_character(pack, status_when_ready=status_when_main)
            return
        page = next_setup_page(provider_ok=provider_ok, character_ok=character_ok)
        if page == "config":
            self.page = "config"
            gaps = provider_config_gaps(
                {
                    "model": self.settings_model,
                    "api_key_set": self.settings_api_key_set,
                }
            )
            self.status = format_config_required_status(gaps)
            self._refresh()
            return
        self.page = "character_select"
        self.status = "Select a character"
        self._refresh()

    def _begin_apply_character(
        self, pack: CharacterPack, *, status_when_ready: str
    ) -> None:
        operation_id = self._begin_operation("applying_character")

        def work() -> None:
            try:
                # Default workspace: omit workspace_path so server uses ~/.amnesia-agent.
                self.client.request_json("POST", "/v1/workspace/setup-or-repair")
                self.client.request_json(
                    "PUT",
                    "/v1/workspace/system-prompt",
                    {"content": pack.prompt},
                )
                invoke(self._character_ready, pack, status_when_ready, operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._character_failed, error, operation_id)

        threading.Thread(target=work, name="assistant-char-apply", daemon=True).start()

    # --- character select ----------------------------------------------------

    def select_character(self, character_id: str) -> None:
        if self.busy or self.operation is not None or not self.ready:
            return
        pack = next((c for c in self.characters if c.id == character_id), None)
        if pack is None:
            self.status = f"Unknown character: {character_id}"
            self._refresh()
            return
        try:
            self.assistant_config = self.config_store.set_selected_character(
                character_id
            )
        except ConfigError as error:
            self.status = f"Config error: {error}"
            self.error = str(error)
            self._refresh()
            return

        if not self.provider_configured:
            self.page = "config"
            self.status = "Character saved — set model and API key to continue"
            self._refresh()
            return

        self.status = f"Loading {pack.display_name}..."
        self._refresh()
        self._begin_apply_character(
            pack, status_when_ready=f"Playing as {pack.display_name}"
        )

    def _character_ready(
        self, pack: CharacterPack, status: str, operation_id: int
    ) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._end_operation(operation_id)
        self.character = pack
        self.current_bg = pack.default_bg
        self.current_expression = pack.default_expression
        self._sync_stage_paths()
        self.last_assistant_text = ""
        self.last_assistant_choices = []
        self.page = "main"
        self.status = status or f"Playing as {pack.display_name}"
        self._refresh()

    def _character_failed(self, error: Exception, operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._end_operation(operation_id)
        self.status = f"Character setup failed: {error}"
        self._refresh()

    def go_character_select(self) -> None:
        if self.busy or self.operation is not None:
            self.status = "Cannot switch character while busy."
            self._refresh()
            return
        self.page = "character_select"
        self.status = "Select a character"
        self._refresh()

    def reset_default_workspace(self) -> None:
        """Confirm then hard-reset ~/.amnesia-agent and re-apply the current character.

        Does not clear ``selected_character_id`` in Assistant home config.
        """
        if self.busy or self.operation is not None or not self.ready:
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
        operation_id = self._begin_operation("resetting_workspace")
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
                invoke(self._reset_ok, pack, operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._reset_failed, error, operation_id)

        threading.Thread(target=work, name="assistant-reset-ws", daemon=True).start()

    def _reset_ok(self, pack: CharacterPack, operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._end_operation(operation_id)
        self.character = pack
        self.current_bg = pack.default_bg
        self.current_expression = pack.default_expression
        self.last_assistant_text = ""
        self.last_assistant_choices = []
        self._sync_stage_paths()
        self.status = "Workspace reset"
        self.error = ""
        self._refresh()

    def _reset_failed(self, error: Exception, operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._end_operation(operation_id)
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
        self.turn_id += 1
        turn_id = self.turn_id
        self.active_turn_id = turn_id
        self.busy = True
        self._sync_stage_paths()
        self.status = "Thinking..."
        self._refresh()
        self.turn_handle = self.client.stream_turn(
            text,
            lambda event, turn_id=turn_id: self._on_event(turn_id, event),
            lambda error, turn_id=turn_id: self._on_error(turn_id, error),
            lambda turn_id=turn_id: self._on_complete(turn_id),
        )

    def choose(self, choice: str) -> None:
        self.send(choice)

    def cancel(self) -> None:
        # Only signal the stream to stop; the terminal callback clears busy.
        if self.turn_handle is None or self.active_turn_id is None:
            return
        self.turn_handle.cancel()
        self.status = "Cancelling..."
        self._refresh()

    def _turn_is_current(self, turn_id: int) -> bool:
        return self.busy and self.active_turn_id == turn_id

    def _cancel_requested(self, turn_id: int) -> bool:
        return (
            self._turn_is_current(turn_id)
            and self.turn_handle is not None
            and self.turn_handle.cancelled
        )

    def _finish_cancelled(self, turn_id: int) -> None:
        if not self._turn_is_current(turn_id):
            return
        self.busy = False
        self.turn_handle = None
        self.active_turn_id = None
        self._sync_stage_paths()
        self.status = "Cancelled"
        self._refresh()

    def _on_event(self, turn_id: int, event: dict[str, Any]) -> None:
        if not self._turn_is_current(turn_id):
            return
        if self._cancel_requested(turn_id):
            self._finish_cancelled(turn_id)
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
            request_id = data.get("request_id")
            self.last_assistant_choices = []
            self.busy = False
            self.turn_handle = None
            self.active_turn_id = None
            self._sync_stage_paths()
            self.status = (
                f"Request failed (reference: {request_id})"
                if isinstance(request_id, str) and request_id
                else "Request failed"
            )
        elif event_type == "done":
            self.busy = False
            self.turn_handle = None
            self.active_turn_id = None
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

    def _on_error(self, turn_id: int, error: Exception) -> None:
        if not self._turn_is_current(turn_id):
            return
        if self._cancel_requested(turn_id):
            self._finish_cancelled(turn_id)
            return
        self.turn_handle = None
        self.active_turn_id = None
        self.busy = False
        self._sync_stage_paths()
        self.last_assistant_choices = []
        if isinstance(error, TurnTimeoutError):
            self.status = (
                "Connection timed out. The provider may still be working."
            )
        else:
            self.status = "Request failed"
        self._refresh()

    def _on_complete(self, turn_id: int) -> None:
        if not self._turn_is_current(turn_id):
            return
        if self._cancel_requested(turn_id):
            self._finish_cancelled(turn_id)
            return
        self.busy = False
        self.turn_handle = None
        self.active_turn_id = None
        self._sync_stage_paths()
        if self.status not in ("Request failed",) and not self.status.startswith(
            "Warning"
        ):
            self.status = "Ready"
        self._refresh()

    # --- config --------------------------------------------------------------

    def go_config(self) -> None:
        if self.busy or self.operation is not None:
            self.status = "Cannot open config while busy."
            self._refresh()
            return
        self.page = "config"
        self.load_config_form()
        self._refresh()

    def leave_config(self) -> None:
        if self.busy or self.operation is not None:
            return
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
        # Re-check readiness: Main only when character is also valid.
        self._route_from_readiness(
            status_when_main=(
                f"Playing as {self.character.display_name}"
                if self.character is not None
                else "Ready"
            )
        )

    def _force_config(self, reason: str) -> None:
        self.page = "config"
        self.status = reason
        self.load_config_form()
        self._refresh()

    def load_config_form(self) -> None:
        if self.operation is not None:
            return
        operation_id = self._begin_operation("loading_config")
        if self.assistant_config is not None:
            self.settings_language = self.assistant_config.language
            self._set_store("settings_language", self.settings_language)
        self.status = "Loading settings..."
        self._refresh()

        def work() -> None:
            try:
                config = self.client.request_json("GET", "/v1/config")
                invoke(self._config_loaded, config, operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._config_failed, error, operation_id)

        threading.Thread(target=work, name="assistant-cfg-load", daemon=True).start()

    def _config_loaded(self, config: dict[str, Any], operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._apply_server_config(config)
        self._end_operation(operation_id)

    def _apply_server_config(
        self, config: dict[str, Any], *, refresh: bool = True
    ) -> None:
        self.settings_model = str(config.get("model") or "")
        self.settings_api_key = ""
        self.settings_api_key_set = bool(config.get("api_key_set"))
        self.settings_base_url = str(config.get("base_url") or "")
        self.settings_provider_params = json.dumps(
            config.get("provider_params") or {}, indent=2
        )
        self.provider_configured = is_provider_configured(config)
        self._set_store("settings_model", self.settings_model)
        self._set_store("settings_api_key", self.settings_api_key)
        self._set_store("settings_base_url", self.settings_base_url)
        self._set_store("settings_provider_params", self.settings_provider_params)
        if refresh:
            if self.provider_configured:
                if self.status.startswith("Loading") or self.status.startswith(
                    "Configure required"
                ):
                    self.status = "Ready"
            else:
                self.status = format_config_required_status(provider_config_gaps(config))
            self._refresh()

    def save_config_form(
        self,
        language: str,
        model: str,
        api_key: str,
        base_url: str,
        provider_params_text: str,
    ) -> None:
        if self.busy or self.operation is not None:
            self.status = "Cannot save config while the agent is busy."
            self._refresh()
            return
        model = (model or "").strip()
        api_key = api_key or ""
        base_url = base_url if base_url is not None else ""
        if not model:
            self.status = "Model is required (no empty default)."
            self._refresh()
            return
        if not api_key.strip() and not self.settings_api_key_set:
            self.status = "API key is required on first run (cannot leave blank)."
            self._refresh()
            return
        try:
            provider_params = json.loads(provider_params_text or "{}")
            if not isinstance(provider_params, dict):
                raise ValueError("Provider params must be a JSON object")
            if language not in SUPPORTED_LANGUAGES:
                raise ValueError(f"Unsupported language: {language}")
            payload: dict[str, Any] = {
                "model": model,
                "base_url": base_url,
                "provider_params": provider_params,
            }
            if api_key.strip():
                payload["api_key"] = api_key.strip()
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.status = f"Invalid settings: {error}"
            self._refresh()
            return
        operation_id = self._begin_operation("saving_config")
        self.status = "Saving settings..."
        self._refresh()

        def work() -> None:
            try:
                # Home store first (local, fail loud) — same order as renpy.
                updated = self.config_store.set_language(language)
                config = self.client.request_json("PUT", "/v1/config", payload)
                invoke(self._config_saved, updated, config, operation_id)
            except Exception as error:  # noqa: BLE001
                invoke(self._config_failed, error, operation_id)

        threading.Thread(target=work, name="assistant-cfg-save", daemon=True).start()

    def _config_saved(
        self,
        assistant_config: AssistantConfig,
        config: dict[str, Any],
        operation_id: int,
    ) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._end_operation(operation_id)
        self.assistant_config = assistant_config
        self.settings_language = assistant_config.language
        self._set_store("settings_language", self.settings_language)
        self._apply_language(assistant_config.language)
        self._apply_server_config(config, refresh=False)
        if not self.provider_configured:
            self.page = "config"
            self.status = format_config_required_status(provider_config_gaps(config))
            self._refresh()
            return
        # Provider ok → Main if character selected+valid, else Character Select.
        self._route_from_readiness(status_when_main="Settings saved")

    def _config_failed(self, error: Exception, operation_id: int) -> None:
        if not self._operation_is_current(operation_id):
            return
        self._end_operation(operation_id)
        self.status = f"Config error: {error}"
        self.error = str(error)
        self._refresh()

    def _apply_language(self, language: str) -> None:
        if renpy is None:
            return
        renpy.change_language(None if language == "english" else language)

    def language_display_name(self) -> str:
        return LANGUAGE_NAMES.get(self.settings_language, "English")

    # --- quit ----------------------------------------------------------------

    def can_quit(self) -> bool:
        return not self.busy and self.operation is None

    def quit_app(self) -> None:
        if not self.can_quit():
            self.status = "Cannot quit while an operation is in progress."
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
