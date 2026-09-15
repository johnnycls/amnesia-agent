# Root shell: routes to the active page.

screen app_shell():
    tag menu
    add Solid("#101820")


    frame:
        style_prefix "app"
        xalign 0.5
        yalign 0.5
        xmaximum 1400
        ymaximum 850
        xfill True
        yfill True
        padding (28, 24)

        vbox:
            spacing 12
            hbox:
                spacing 12
                text _("Amnesia Agent") style "app_title"
                text app.status style "app_small" yalign 0.5

            if app.page == "loading":
                use loading_page
            elif app.page == "workspace_select":
                use workspace_select_page
            elif app.page == "workspace_invalid":
                use workspace_invalid_page
            elif app.page == "main":
                use main_page
            elif app.page == "workspace_settings":
                use workspace_settings_page
            elif app.page == "history":
                use history_page
            elif app.page == "config":
                use config_page
            else:
                text _("Unknown page") style "app_text"
