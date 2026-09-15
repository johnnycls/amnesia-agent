# Amnesia Agent Ren'Py frontend entry.

default input_text = ""
default settings_model = ""
default settings_api_key = ""
default settings_base_url = ""
default settings_provider_params = "{}"
default settings_timeout = "1800"
default settings_output_limit = "262144"
default settings_context_limit = "1000"
default settings_language = "english"
default system_prompt_text = ""
default memory_text = ""
default history_dates = []
default history_selected_date = ""
default history_content = "[]"

init python:
    from state.app import AppState, localize

    app = AppState()

    def quit_action():
        if app.busy:
            app.status = localize("Cannot quit while the agent is busy.")
            renpy.restart_interaction()
            return
        app.quit_app()

    config.quit_action = Function(quit_action)

label start:
    $ app.start_loading()
    call screen app_shell
    $ app.stop()
    return
