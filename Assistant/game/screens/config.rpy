screen config_page():
    vbox:
        spacing 14
        hbox:
            spacing 12
            if app.provider_configured:
                textbutton "Back" action Function(app.leave_config)
            text "Config" size 28 bold True

        text "Model and API key are required before turns. Workspace stays ~/.amnesia-agent." style "app_small"
        if not app.provider_configured:
            text "Missing: set a real model id and an API key (first run)." style "app_small"

        text "Model" style "app_small"
        input value VariableInputValue("settings_model") xfill True length 200

        text "API key" style "app_small"
        if app.settings_api_key_set:
            text "API key is set (leave blank when saving to keep it)" style "app_small"
        else:
            text "API key is not set — enter a key to continue" style "app_small"
        input value VariableInputValue("settings_api_key") xfill True length 200 mask "*"

        hbox:
            spacing 12
            textbutton "Save" action Function(app.save_config_form, settings_model, settings_api_key) sensitive (not app.busy)
