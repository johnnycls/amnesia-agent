screen main_page():
    vbox:
        spacing 14
        hbox:
            spacing 10
            textbutton _("Back") action Function(app.go_workspace_select)
            textbutton _("Workspace Settings") action Function(app.go_workspace_settings)
            textbutton _("History") action Function(app.go_history)
            textbutton _("Config") action Function(app.go_config)

        text _("Workspace:") style "app_small"
        text "[app.workspace_path]" style "app_small"

        text _("Last assistant message") size 22 bold True
        viewport:
            ymaximum 420
            mousewheel True
            draggable True
            scrollbars "vertical"
            vbox:
                spacing 10
                if app.streaming_text:
                    text "[app.streaming_text]" style "app_text"
                elif app.last_assistant_text:
                    text "[app.last_assistant_text]" style "app_text"
                else:
                    text _("No assistant message yet.") style "app_small"

        if app.last_assistant_choices and not app.busy:
            text _("Options") size 20 bold True
            hbox:
                spacing 10
                for choice in app.last_assistant_choices:
                    textbutton choice action Function(app.choose, choice)

        hbox:
            spacing 10
            if app.busy:
                text _("Input disabled while agent is busy.") style "app_small" yalign 0.5
            else:
                input:
                    value VariableInputValue("input_text")
                    xfill True
                    length 400
                    pixel_width 900
                    style "app_text"
            textbutton _("Send") sensitive (not app.busy and app.ready) action Function(app.send, input_text)
            textbutton _("Cancel") sensitive app.busy action Function(app.cancel)
