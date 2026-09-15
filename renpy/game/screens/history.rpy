screen history_page():
    vbox:
        spacing 12
        hbox:
            spacing 10
            textbutton _("Back") action Function(app.go_main)
            text _("History") size 28 bold True

        text _("Dates") size 22 bold True
        viewport:
            ymaximum 160
            mousewheel True
            scrollbars "vertical"
            vbox:
                spacing 6
                for date in history_dates:
                    textbutton date action Function(app.load_history_date, date)

        text "[_('Selected:')] [history_selected_date]" style "app_small"
        viewport:
            ymaximum 400
            mousewheel True
            draggable True
            scrollbars "vertical"
            text history_content style "app_small"

        textbutton _("Clear all history") action Confirm(_("Clear all history?"), Function(app.clear_history))
