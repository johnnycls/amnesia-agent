screen loading_page():
    vbox:
        spacing 16
        text _("Loading") size 28 bold True
        text app.status style "app_small"
        if app.error:
            text "[app.error]" color "#ff8d8d" style "app_text"
            textbutton _("Retry") action Function(app.start_loading)
        elif app.starting:
            text _("Please wait...") style "app_small"
