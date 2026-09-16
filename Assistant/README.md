# Assistant

A Ren'Py visual-novel-style frontend for `amnesia-agent`. Open this folder with the
Ren'Py launcher.

**Locked boot** (like renpy recent-workspace auto-enter): once provider creds and a
character choice are complete, later launches skip setup and open **Main** directly.
Persists `persistent.selected_character_id` and `persistent.assistant_language` in
Ren'Py persistent storage (default language `english`). Always uses the default
workspace (`~/.amnesia-agent`, by omitting `workspace_path`). Slim **Config** page for
`model`, `api_key`, `base_url`, `provider_params` via
`GET`/`PUT /v1/config`, plus UI language. No workspace picker in v1.

## Requirements

```text
pip install ./kernel
pip install ./local_server
```

On first run the game gates until **both** are ready:

1. **Provider** — non-empty `model` and an API key saved. Later Config saves omit a
   blank API key field so the stored key is kept (clearing the key from the UI is
   not supported). Prefer **Config** first when these are missing.
2. **Character** — `selected_character_id` in Assistant home config matching a
   bundled pack. Prefer **Character Select** when provider is ok but character is
   missing/invalid.

Set `AMNESIA_AGENT_PYTHON` if the game must spawn a specific Python for
`python -m amnesia_agent_local_server`.

## Run

1. Install kernel + local_server (above).
2. Open the `Assistant/` project in the Ren'Py SDK launcher (8.5+ recommended).
3. Click Launch / Run. The game spawns the local server, health-checks
   `instance_id`, loads `/v1/config` and Ren'Py persistent preferences, then:
   - **Both ready** → apply character (setup-or-repair; prompt injected per turn) → **Main**
   - Missing model/API key → **Config** (cannot proceed without save success)
   - Missing/invalid character → **Character Select**
   - Corrupt Assistant preferences → offer **Reset Assistant preferences**, then reload setup
   - Valid `.amod` files in the per-user mod inbox → install automatically before character loading
   - Corrupt local-server settings → offer **Reset server settings** (clears provider credentials), then reload setup

## Architecture

```text
Assistant/game/
  api/          # HTTP JSON + SSE (Client, TurnHandle, ASSISTANT_STAGE)
  process/      # spawn / poll / shutdown local_server
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

Every pack must provide at least one background plus transparent `neutral` and `busy` expressions. All frames in an animation must share dimensions and transparency. Frame names must be consecutive (`0001.png`, `0002.png`, ...). WebM and other video assets are not supported.

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
5. Put every background under `bg/<id>/` and every expression under
   `expressions/<id>/`.
6. Put numbered PNG frames (`0001.png`, `0002.png`, ...) and this metadata in every
   asset directory:

   ```json
   {"type": "png_sequence", "fps": 8, "loop": true}
   ```

7. Add a root-level `manifest.json` with the same ID/display name and a semantic version.
8. ZIP the archive contents directly, without an extra parent folder, and rename it to
   `.amod`.
9. Copy the `.amod` into the installed build's per-user `mods/inbox` directory.
10. Start the Assistant. Valid archives install automatically; invalid archives remain
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
  written to Assistant home config and applied (`renpy.change_language`). If selected
  character is still valid → apply + **Main**; else **Character Select**. Cannot leave
  Config until model + API key are set.
- **Reset** (Main / Character Select): Confirm → `POST /v1/workspace/create-or-reset`
  on the default workspace (hard wipe), preserve the frontend prompt for per-turn injection,
  clear message/choices, restore the default background and `neutral` expression. Does **not** clear
  Assistant `selected_character_id`.
- Cancel closes the SSE connection; busy clears on complete (same contract as renpy).
- `POST /v1/turn` with `response_format` `assistant_stage`:
  `message`, `choices`, `bg`, `expression`.
- Unknown `bg` / `expression` ids keep the previous stage and set a status warning.
- Quit blocked while busy; otherwise `POST /v1/shutdown` then exit.

## Tests

Unit tests do not need Ren'Py:

```text
cd Assistant && python -m unittest discover -t . -s tests -v
```

## v1 non-goals

No STT, TTS, Live2D, character editor, voice, or workspace picker. Config covers
model, api_key, base_url, provider_params, and language (execution-limit knobs and
other local_server fields can wait). Character choice and language are persisted by
Ren'Py; switching characters is still available from Main.
