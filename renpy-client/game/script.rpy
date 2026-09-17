# Assistant Ren'Py frontend entry.

default input_text = ""
default settings_model = ""
default settings_api_key = ""
default settings_base_url = ""
default settings_provider_params = "{}"
default settings_language = "english"

init python:
    import sys

    from state.app import AppState

    app = AppState()
    for _launch_argument in sys.argv[1:]:
        if isinstance(_launch_argument, str) and _launch_argument.lower().startswith("amnesia://"):
            app.receive_deep_link(_launch_argument)

    def quit_action():
        if not app.can_quit():
            app.status = "Cannot quit while an operation is in progress."
            renpy.restart_interaction()
            return
        app.quit_app()

    config.quit_action = Function(quit_action)

label start:
    $ app.start_loading()
    call screen app_shell
    $ app.stop()
    return
