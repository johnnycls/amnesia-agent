# Project metadata for the Assistant Ren'Py client.

define config.name = "Assistant"
define config.version = "0.0.0-alpha.0"
define config.save_directory = "amnesia-assistant"
define build.name = "amnesia-assistant"
define build.version = "0.0.0-alpha.0"

init python:
    # Keep bundled character packs as ordinary files: the loader scans their
    # directories at runtime, while community mods live outside the install.
    build.classify("game/characters/**", "all")

    # Optional CI-built native sidecar (same layout as renpy/).
    build.classify("game/server/**", "all")
    build.executable("game/server/**")
