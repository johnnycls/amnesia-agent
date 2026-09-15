screen config_page():
    vbox:
        spacing 10
        hbox:
            spacing 10
            textbutton _("Back") action Function(app.go_main)
            text _("Config") size 28 bold True

        viewport:
            mousewheel True
            draggable True
            scrollbars "vertical"
            ymaximum 700
            vbox:
                spacing 10

                text _("Interface language") size 24 bold True
                text "[_('Current language:')] [app.language_display_name()]" style "app_small"
                hbox:
                    spacing 8
                    textbutton "English" action SetVariable("settings_language", "english")
                    textbutton "简体中文" action SetVariable("settings_language", "schinese")
                    textbutton "繁體中文" action SetVariable("settings_language", "tchinese")
                    textbutton "日本語" action SetVariable("settings_language", "japanese")
                    textbutton "한국어" action SetVariable("settings_language", "korean")

                text _("Provider") size 24 bold True
                text _("Model") style "app_small"
                input value VariableInputValue("settings_model") xfill True
                text _("API key (leave blank to keep the current key)") style "app_small"
                if app.settings_api_key_set:
                    text _("API key is set") style "app_small"
                input value VariableInputValue("settings_api_key") xfill True mask "*"
                text _("Base URL") style "app_small"
                input value VariableInputValue("settings_base_url") xfill True
                text _("Provider params (JSON object)") style "app_small"
                input value VariableInputValue("settings_provider_params") xfill True multiline True ymaximum 100

                text _("Execution limits") size 24 bold True
                text _("Command timeout seconds") style "app_small"
                input value VariableInputValue("settings_timeout") xfill True
                text _("Maximum command output bytes") style "app_small"
                input value VariableInputValue("settings_output_limit") xfill True
                text _("Maximum context message characters") style "app_small"
                input value VariableInputValue("settings_context_limit") xfill True

                hbox:
                    spacing 10
                    textbutton _("Save settings") action Function(
                        app.save_config_form,
                        settings_language,
                        settings_model,
                        settings_api_key,
                        settings_base_url,
                        settings_provider_params,
                        settings_timeout,
                        settings_output_limit,
                        settings_context_limit,
                    )

                text _("Reset") size 24 bold True
                text _("Reset local server: POST /v1/config/reset (model, API key, timeouts…).") style "app_small"
                text _("Reset Ren'Py: rewrite ~/.amnesia-agent-renpy/config.json defaults (language=english, recent workspaces cleared).") style "app_small"
                hbox:
                    spacing 10
                    textbutton _("Reset local server settings") action Confirm(_("Restore default local server settings?"), Function(app.reset_local_server_config))
                    textbutton _("Reset Ren'Py settings") action Confirm(_("Restore default Ren'Py settings?"), Function(app.reset_renpy_config))
