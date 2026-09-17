screen loading_page():
    vbox:
        spacing 16
        text "Loading" size 28 bold True
        text app.status style "app_small"
        if app.error:
            if app.loading_recovery == "server_connection":
                text "No available server connection. Scan a server pairing QR code with this device, then open Ren'Py from the pairing link." style "app_small"
            elif app.loading_recovery == "server_config":
                text "The server settings are corrupt. Resetting them removes the stored API key and provider settings." style "app_small"
                textbutton "Reset server settings" action Function(app.reset_server_config)
            elif app.loading_recovery == "assistant_config":
                text "Assistant preferences are corrupt. Resetting them clears the selected character and interface language." style "app_small"
                textbutton "Reset Assistant preferences" action Function(app.reset_assistant_config)
            text "[app.error]" color "#ff8d8d" style "app_text"
            textbutton "Retry" action Function(app.start_loading)
        elif app.operation:
            text "Please wait..." style "app_small"
