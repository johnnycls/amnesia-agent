screen character_select_page():
    vbox:
        spacing 14
        text "Choose a character" style "app_title"
        text "Click a portrait to apply it. Import community mods from Mod Manager." style "app_small"

        hbox:
            spacing 10
            textbutton "Config" action Function(app.go_config) sensitive (not app.busy)
            textbutton "Mod Manager" action Function(app.go_mod_manager) sensitive (not app.busy)

        hbox:
            spacing 10
            textbutton "←" action Function(app.scroll_character_list, -1) sensitive (len(app.characters) > 0)
            viewport id "character_viewport":
                xfill True
                ymaximum 470
                mousewheel "horizontal"
                draggable True
                arrowkeys True
                hbox:
                    spacing 18
                    for character in app.characters:
                        button:
                            style "character_card"
                            selected (app.character is not None and app.character.id == character.id)
                            action Function(app.select_character, character.id)
                            vbox:
                                spacing 8
                                xalign 0.5
                                $ portrait = app.character_portrait_displayable(character)
                                if portrait:
                                    add portrait xysize (240, 360) fit "contain"
                                text character.display_name style "character_card_name" xalign 0.5 textalign 0.5
            textbutton "→" action Function(app.scroll_character_list, 1) sensitive (len(app.characters) > 0)

        if app.mod_messages:
            text "Some installed mods could not be loaded:" style "app_small"
            viewport:
                ymaximum 100
                mousewheel True
                vbox:
                    for message in app.mod_messages:
                        text message style "app_small"

screen mod_manager_page():
    vbox:
        spacing 14
        hbox:
            spacing 12
            textbutton "Back" action Function(app.go_character_select)
            text "Mod Manager" style "app_title"

        text "Import one .amod character archive at a time." style "app_small"
        textbutton "Import .amod" action Function(app.import_mod) sensitive (not app.busy and app.operation is None)

        if app.mod_manager_status:
            text app.mod_manager_status style "app_small"

        text "Installed character mods" size 24 bold True
        viewport:
            ymaximum 420
            mousewheel True
            vbox:
                spacing 8
                for character in app.installed_characters():
                    frame:
                        background "#263746"
                        padding (12, 10)
                        hbox:
                            spacing 14
                            text "[character.display_name] ([character.id])" style "app_small" xfill True
                            textbutton "Remove" action Function(app.remove_mod, character.id)
                if not app.installed_characters():
                    text "No installed community mods." style "app_small"

        if app.mod_messages:
            text "Installed character load errors" size 24 bold True
            viewport:
                ymaximum 180
                mousewheel True
                vbox:
                    for message in app.mod_messages:
                        text message style "app_small"
