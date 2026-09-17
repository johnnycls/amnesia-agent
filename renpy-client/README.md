# renpy-client

A Ren'Py visual-novel-style frontend for `amnesia-agent`. Open this folder with the
Ren'Py launcher.

**Locked boot** (like renpy recent-workspace auto-enter): once provider creds and a
character choice are complete, later launches skip setup and open **Main** directly.
Persists `persistent.selected_character_id`, `persistent.assistant_language`, and
`persistent.server_url` in Ren'Py persistent storage (default language `english`,
default server URL `http://127.0.0.1:8765`). Always uses the default
workspace (`~/.amnesia-agent`, by omitting `workspace_path`). Slim **Config** page for
`model`, `api_key`, `base_url`, `provider_params` via
`GET`/`PUT /v1/config`, plus UI language. No workspace picker in v1.

## Requirements

```text
pip install ./kernel
pip install ./server
```

On first run the game gates until **both** are ready:

1. **Provider** — non-empty `model` and an API key saved. Later Config saves omit a
   blank API key field so the stored key is kept (clearing the key from the UI is
   not supported). Prefer **Config** first when these are missing.
2. **Character** — `selected_character_id` in Ren'Py client home config matching a
   bundled pack. Prefer **Character Select** when provider is ok but character is
   missing/invalid.

The Ren'Py frontend is client-only. It checks the bundled/local origin
`http://127.0.0.1:8765` first, then an authenticated persisted server origin. The
Loading screen has no server URL input; it provides Retry and expects remote
onboarding through an operating-system `amnesia://pair` link. Pairing codes are
single-use and short-lived; successful pairing persists the server origin and
per-device bearer token. HTTP JSON and SSE requests send that token when one is
configured. Remote servers must use HTTPS and expose only the authenticated API.
The kernel still exposes powerful agent tools, so remote deployments are
single-owner only and must not be treated as multi-tenant sandboxes.

For exported packs, use the native `local-renpy-launcher` beside the fixed-layout
server and Ren'Py executable. The launcher starts the bundled server, waits for
its matching `instance_id`, starts Ren'Py, then shuts down only the server it
started. It fails fast if the bundled server cannot start.

## Run

1. Install kernel + server (above).
2. Open the `renpy-client/` project in the Ren'Py SDK launcher (8.5+ recommended).
3. Click Launch / Run. For development, start `amnesia-agent-server`
   separately. For an exported pack, start the platform `local-renpy-launcher`.
   The launcher starts the bundled server first; Ren'Py health-checks the
   persisted origin, loads `/v1/config` and persistent preferences, then:
   - **Both ready** → apply character (setup-or-repair; prompt injected per turn) → **Main**
   - Missing model/API key → **Config** (cannot proceed without save success)
   - Missing/invalid character → **Character Select**
   - Corrupt Ren'Py client preferences → offer **Reset Ren'Py client preferences**, then reload setup
   - Valid `.amod` files in the per-user mod inbox → install automatically before character loading
   - Corrupt server settings → offer **Reset server settings** (clears provider credentials), then reload setup

## Architecture

```text
renpy-client/game/
  api/          # HTTP JSON + SSE (Client, TurnHandle, ASSISTANT_STAGE)
  audio/        # shared looping music service and channel ownership
  state/        # AppState + stage apply + readiness helpers
  home_config/  # Ren'Py persistent preferences (JSON adapter is test-only)
  characters/   # bundled packs, mod loader, and .amod store
  screens/      # loading, config, character_select, mod_manager, main
  script.rpy / options.rpy
```

Standalone frontend — no cross-package imports. Patterns were copied slim
(including home JSON store with `chmod 0600` writes).

## Characters

Each pack lives under `game/characters/<id>/` and uses animation directories:

| File | Role |
|---|---|
| `character.json` | id, display name, default background ID |
| `prompt.md` | frontend-owned prompt injected per turn; never written to the kernel workspace |
| `bg/<id>/animation.json` | animation type, FPS, and loop setting |
| `bg/<id>/0001.png` | numbered background frames |
| `expressions/<id>/animation.json` | animation metadata for an expression |
| `expressions/<id>/0001.png` | numbered transparent expression frames |
| `bgm/<id>.ogg` | looping OGG music track; `default.ogg` is required |

Every pack must provide at least one background, transparent `neutral` and `busy` expressions, and `bgm/default.ogg`. BGM files must be non-empty OGG files no larger than 25 MiB each. All frames in an animation must share dimensions and transparency. Frame names must be consecutive (`0001.png`, `0002.png`, ...). WebM and other video assets are not supported.

### Community mods

A community mod is a root-layout `.amod` ZIP:

```text
manifest.json
character.json
prompt.md
bg/<id>/animation.json
bg/<id>/0001.png
expressions/<id>/animation.json
expressions/<id>/0001.png
bgm/default.ogg
```

Required manifest fields are `format` (`amnesia-character`), `schema_version` (`1`),
`id`, `version` (semantic `major.minor.patch`), and `display_name`. Bundled and
exported packs also carry the same semantic `version` in `character.json`. Copy downloaded
`.amod` files into the per-user `mods/inbox` directory. Valid archives are installed
automatically at startup and removed from the inbox. Invalid archives remain with a
`.error.txt` explanation. Installed mods are loaded from the Ren'Py per-user save
directory, not from the application directory.

The Character Select screen uses a horizontally scrollable list of clickable animated
portrait cards. Bundled and community characters are sorted by display name. Use the
Mod Manager to export a character as `.amod`, inspect rejected archives, or remove an
installed mod.

### Manual mod creation

1. Copy an existing character pack as a template.
2. Rename its folder to a unique lowercase ID such as `creator.moon_priestess`.
3. Update `character.json` so `id`, `display_name`, and `default_bg` match the new pack.
4. Edit `prompt.md`.
5. Put every background under `bg/<id>/`, every expression under
   `expressions/<id>/`, and every looping music track under `bgm/<id>.ogg`.
   Include the required `bgm/default.ogg`.
6. Put numbered PNG frames (`0001.png`, `0002.png`, ...) and this metadata in every
   asset directory:

   ```json
   {"type": "png_sequence", "fps": 8, "loop": true}
   ```

7. Add a root-level `manifest.json` with the same ID/display name and a semantic version.
8. ZIP the archive contents directly, without an extra parent folder, and rename it to
   `.amod`.
9. Copy the `.amod` into the installed build's per-user `mods/inbox` directory.
10. Start the Ren'Py client. Valid archives install automatically; invalid archives remain
    with an adjacent `.error.txt` explanation.

### Art direction

Color-block moe style: limited palette (3–5 groups), no lineart, two-step shadows,
extreme foreshortening / dynamic poses, ~6.5–7.5 head proportions. Bundled Aurora/Kai
expressions and backgrounds are generated illustrations matching this direction (not PIL solids).


## Main behaviour

- Layers: background, character sprite, message text, choice buttons, input.
- Input always visible; **Send** when idle, **Cancel** when busy.
- While `app.busy`, Main shows the character's **`busy`** sprite (UI-only). The LLM
  still emits `expression` among `neutral` / `smile` / `think` only.
- **Character Select**: saves `selected_character_id`, then **Main** if provider ok,
  else **Config**.
- **Config save**: model + API key still required; `base_url` may be empty (provider
  default); `provider_params` is a JSON object (`{}` ok) — invalid JSON / non-object
  fails in the UI; server **400** for secret-shaped keys is surfaced. Language is
  written to Ren'Py client home config and applied (`renpy.change_language`). If selected
  character is still valid → apply + **Main**; else **Character Select**. Cannot leave
  Config until model + API key are set.
- **Reset** (Main / Character Select): Confirm → `POST /v1/workspace/create-or-reset`
  on the default workspace (hard wipe), preserve the frontend prompt for per-turn injection,
  clear message/choices, restore the default background and `neutral` expression. Does **not** clear
  Ren'Py client `selected_character_id`.
- Cancel closes the SSE connection; busy clears on complete (same contract as renpy).
- `POST /v1/turn` with `response_format` `assistant_stage`:
  `message`, `choices`, `bg`, `expression`, `bgm`.
- Unknown `bg` / `expression` / `bgm` ids keep the previous stage and set a status warning.
- Character `default` BGM starts automatically, loops, and is not restarted when the same track is applied again.
- Quit blocked while busy; Ren'Py cancels active turns and exits. The exported
  launcher, not Ren'Py, sends `POST /v1/shutdown` and owns server cleanup.

## Exported pack layout

The native launcher uses these platform-default paths relative to itself:

```text
pack/
  local-renpy-launcher(.exe)
  server/amnesia-agent-server(.exe)
  Assistant.exe                         # Windows
  Assistant                             # Linux
  Assistant.app/Contents/MacOS/Assistant # macOS
```

CI cross-builds launcher artifacts for Windows amd64, Linux amd64, macOS amd64,
and macOS arm64. Copy the matching launcher and a native server executable into
the Ren'Py export. The current Ren'Py build configuration includes
`game/server/**` when that server executable is supplied; the release assembly
step remains responsible for placing the native files beside the exported game.

The launcher always starts its bundled server on `127.0.0.1:8765`, even when the
user has persisted a different trusted URL. Ren'Py may connect to that external
URL; the launcher still shuts down the bundled child when Ren'Py exits.

## Tests

Unit tests do not need Ren'Py:

```text
cd renpy-client && python -m unittest discover -t . -s tests -v
```

## v1 non-goals

No STT, TTS, Live2D, character editor, voice, or workspace picker. Config covers
model, api_key, base_url, provider_params, and language (execution-limit knobs and
other server fields can wait). Character choice and language are persisted by
Ren'Py; switching characters is still available from Main.
