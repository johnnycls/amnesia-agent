screen main_page():
    # Character sprite (right-ish)
    if app.sprite_path:
        add app.sprite_path:
            xalign 0.82
            yalign 1.0
            yoffset 40
            zoom 0.85

    # Top bar
    frame:
        background "#000000aa"
        xfill True
        padding (20, 12)
        hbox:
            spacing 16
            textbutton "Characters" action Function(app.go_character_select)
            textbutton "Config" action Function(app.go_config) sensitive (not app.busy)
            textbutton "Reset" action Function(app.reset_default_workspace) sensitive (not app.busy and app.character is not None)
            if app.character:
                text app.character.display_name style "app_small" yalign 0.5
            text app.status style "app_small" yalign 0.5

    # Message + choices panel
    frame:
        background "#101820cc"
        xalign 0.5
        yalign 0.92
        xmaximum 1600
        xfill True
        padding (24, 18)

        vbox:
            spacing 12
            viewport:
                ymaximum 180
                mousewheel True
                scrollbars "vertical"
                vbox:
                    if app.last_assistant_text:
                        text "[app.last_assistant_text]" style "app_message"
                    else:
                        text "Say something to begin." style "app_small"

            if app.last_assistant_choices and not app.busy:
                hbox:
                    spacing 10
                    for choice in app.last_assistant_choices:
                        textbutton choice action Function(app.choose, choice)

            hbox:
                spacing 10
                input:
                    value VariableInputValue("input_text")
                    xfill True
                    length 400
                    pixel_width 1100
                    style "app_text"
                if app.busy:
                    textbutton "Cancel" action Function(app.cancel)
                else:
                    textbutton "Send" sensitive app.ready action Function(app.send, input_text)
