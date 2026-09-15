screen workspace_settings_page():
    vbox:
        spacing 12
        hbox:
            spacing 10
            textbutton _("Back") action Function(app.go_main)
            text _("Workspace Settings") size 28 bold True

        text _("System prompt") size 22 bold True
        input value VariableInputValue("system_prompt_text") multiline True xfill True ymaximum 250
        hbox:
            spacing 8
            textbutton _("Save prompt") action Function(app.save_system_prompt, system_prompt_text)
            textbutton _("Reset prompt") action Confirm(_("Reset the system prompt?"), Function(app.reset_system_prompt))

        text _("Memory") size 22 bold True
        input value VariableInputValue("memory_text") multiline True xfill True ymaximum 250
        hbox:
            spacing 8
            textbutton _("Save memory") action Function(app.save_memory, memory_text)
