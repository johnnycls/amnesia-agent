screen character_select_page():
    vbox:
        spacing 18
        text "Choose a character" size 28 bold True
        text "Default workspace ~/.amnesia-agent" style "app_small"
        hbox:
            spacing 12
            textbutton "Config" action Function(app.go_config) sensitive (not app.busy)

        hbox:
            spacing 28
            for character in app.characters:
                vbox:
                    spacing 10
                    xmaximum 320
                    if character.portrait_path():
                        add character.portrait_path() xysize (240, 360)
                    text character.display_name size 24 bold True
                    textbutton "Play" action Function(app.select_character, character.id)
