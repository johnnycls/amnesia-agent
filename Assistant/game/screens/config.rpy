screen config_page():
    vbox:
        spacing 14
        hbox:
            spacing 12
            if app.provider_configured:
                textbutton "Back" action Function(app.leave_config)
            text "Config" size 28 bold True

        text "Model and API key are required before turns. base_url / provider_params may be empty. Workspace stays ~/.amnesia-agent." style "app_small"
        if not app.provider_configured:
            text "Missing: set a real model id and an API key (first run)." style "app_small"

        text "Interface language" size 22 bold True
        text "Current language: [app.language_display_name()]" style "app_small"
        hbox:
            spacing 8
            textbutton "English" action SetVariable("settings_language", "english")
            textbutton "简体中文" action SetVariable("settings_language", "schinese")
            textbutton "繁體中文" action SetVariable("settings_language", "tchinese")
            textbutton "日本語" action SetVariable("settings_language", "japanese")
            textbutton "한국어" action SetVariable("settings_language", "korean")

        text "Model" style "app_small"
        input value VariableInputValue("settings_model") xfill True length 200

        text "API key" style "app_small"
        if app.settings_api_key_set:
            text "API key is set (leave blank when saving to keep it)" style "app_small"
        else:
            text "API key is not set — enter a key to continue" style "app_small"
        input value VariableInputValue("settings_api_key") xfill True length 200 mask "*"

        text "Base URL (empty = provider default)" style "app_small"
        input value VariableInputValue("settings_base_url") xfill True length 400

        text "Provider params (JSON object)" style "app_small"
        input value VariableInputValue("settings_provider_params") xfill True multiline True ymaximum 100

        hbox:
            spacing 12
            textbutton "Save" action Function(
                app.save_config_form,
                settings_language,
                settings_model,
                settings_api_key,
                settings_base_url,
                settings_provider_params,
            ) sensitive (not app.busy)


        null height 24
        text "Danger zone" size 22 bold True
        text "Hard-reset deletes everything under ~/.amnesia-agent, then re-applies the current character prompt. Infrequent — confirm carefully." style "app_small"
        textbutton "Reset default workspace…" action Function(app.reset_default_workspace) sensitive (not app.busy and app.character is not None)
