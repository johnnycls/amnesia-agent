# Assistant Ren'Py frontend entry.

default input_text = ""
default settings_model = ""
default settings_api_key = ""
default settings_base_url = ""
default settings_provider_params = "{}"
default settings_language = "english"

init python:
    from state.app import AppState

    app = AppState()

    def quit_action():
        if app.busy:
            app.status = "Cannot quit while the agent is busy."
            renpy.restart_interaction()
            return
        app.quit_app()

    config.quit_action = Function(quit_action)

label start:
    $ app.start_loading()
    call screen app_shell
    $ app.stop()
    return
