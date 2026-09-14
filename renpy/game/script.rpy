# Amnesia Agent Ren'Py frontend.

default active_tab = "chat"
default input_text = ""
default persistent.ui_language = "english"
default settings_model = ""
default settings_api_key = ""
default settings_base_url = ""
default settings_provider_params = "{}"
default settings_timeout = "1800"
default settings_output_limit = "262144"
default settings_context_limit = "1000"
default system_prompt_text = ""
default memory_text = ""
default history_dates = []
default history_selected_date = ""
default history_content = "[]"

init python:
    import json

    from agent_controller import AgentController, _localized

    LANGUAGE_NAMES = {
        "english": "English",
        "schinese": "简体中文",
        "tchinese": "繁體中文",
        "japanese": "日本語",
        "korean": "한국어",
    }

    def set_ui_language(language):
        if language not in LANGUAGE_NAMES:
            return
        persistent.ui_language = language
        renpy.change_language(None if language == "english" else language)
        renpy.save_persistent()
        renpy.restart_interaction()

    def apply_saved_language():
        language = getattr(persistent, "ui_language", "english")
        if language not in LANGUAGE_NAMES:
            language = "english"
            persistent.ui_language = language
        renpy.change_language(None if language == "english" else language)

    def language_name():
        return LANGUAGE_NAMES.get(
            getattr(persistent, "ui_language", "english"), "English"
        )

    controller = AgentController()

    def save_settings_action():
        try:
            provider_params = json.loads(settings_provider_params or "{}")
            if not isinstance(provider_params, dict):
                raise ValueError("Provider params must be a JSON object")
            controller.save_settings(
                {
                    "model": settings_model,
                    "api_key": settings_api_key,
                    "base_url": settings_base_url,
                    "provider_params": provider_params,
                    "command_timeout_seconds": float(settings_timeout),
                    "max_command_output_bytes": int(settings_output_limit),
                    "max_context_message_chars": int(settings_context_limit),
                }
            )
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            controller.status = _localized("Invalid settings: {error}", error=error)
            controller._refresh()

    def save_prompt_action():
        controller.save_system_prompt(system_prompt_text)

    def save_memory_action():
        controller.save_memory(memory_text)

label start:
    $ apply_saved_language()
    $ controller.start_async()
    call screen agent_shell
    $ controller.stop()
    return
