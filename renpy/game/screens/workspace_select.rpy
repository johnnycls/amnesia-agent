screen workspace_select_page():
    vbox:
        spacing 14
        text _("Workspace Select") size 28 bold True

        text _("Recent workspaces") size 22 bold True
        viewport:
            ymaximum 280
            mousewheel True
            draggable True
            scrollbars "vertical"
            vbox:
                spacing 8
                if not app.recent_workspaces():
                    text _("No recent workspaces") style "app_small"
                for entry in app.recent_workspaces():
                    hbox:
                        spacing 10
                        textbutton "[entry['path']]" action Function(app.open_workspace, entry["path"])
                        text "[entry['last_opened_at']]" style "app_small" yalign 0.5
                        textbutton _("Delete") action Function(app.delete_recent, entry["path"])

        text _("Import workspace path") size 22 bold True
        hbox:
            spacing 10
            input value VariableInputValue("import_path") xfill True length 400
            textbutton _("Open") action Function(app.open_workspace, import_path)

        text _("Create workspace path") size 22 bold True
        hbox:
            spacing 10
            input value VariableInputValue("create_path") xfill True length 400
            textbutton _("Create") action Function(app.create_workspace, create_path)

screen workspace_invalid_page():
    vbox:
        spacing 16
        text _("Workspace is not valid") size 28 bold True
        text _("Path:") style "app_small"
        text "[app.pending_workspace_path]" style "app_text"
        text _("Choose setup or repair (keep files) or create or reset (wipe).") style "app_small"
        hbox:
            spacing 12
            textbutton _("Setup or repair") action Function(app.resolve_workspace_choice, "setup_or_repair")
            textbutton _("Create or reset") action Confirm(_("Wipe and recreate this workspace?"), Function(app.resolve_workspace_choice, "create_or_reset"))
            textbutton _("Back") action Function(app.go_workspace_select)
