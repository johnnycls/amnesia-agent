# Root shell: routes to the active page.

screen app_shell():
    tag menu

    if app.page == "main" and app.bg_path:
        add app.bg_path xysize (1920, 1080)
    else:
        add Solid("#101820")

    if app.page == "main":
        use main_page
    else:
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
                    text "Assistant" style "app_title"
                    text app.status style "app_small" yalign 0.5

                if app.page == "loading":
                    use loading_page
                elif app.page == "character_select":
                    use character_select_page
                elif app.page == "config":
                    use config_page
                else:
                    text "Unknown page" style "app_text"

    if app.operation:
        use operation_overlay

screen operation_overlay():
    modal True
    zorder 100

    add Solid("#000000bb")

    frame:
        xalign 0.5
        yalign 0.5
        xmaximum 620
        xfill True
        padding (36, 30)
        background "#101820ee"

        vbox:
            spacing 16
            xalign 0.5
            text "[app.spinner_frame()]" size 48 xalign 0.5
            text app.status style "app_text" xalign 0.5 textalign 0.5
            text "Please wait..." style "app_small" xalign 0.5
            timer 0.12 repeat True action Function(app.advance_spinner)
