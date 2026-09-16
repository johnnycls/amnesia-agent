# Assistant

A Ren'Py visual-novel-style frontend for `amnesia-agent`. Open this folder with the
Ren'Py launcher (separate from [`renpy/`](../renpy/)).

**Locked boot** (like renpy recent-workspace auto-enter): once provider creds and a
character choice are complete, later launches skip setup and open **Main** directly.
Persists `selected_character_id` and `language` in
`~/.amnesia-agent-assistant/config.json` (default language `english`). Always
uses the default workspace (`~/.amnesia-agent`, by omitting `workspace_path`). Slim
**Config** page for `model`, `api_key`, `base_url`, `provider_params` via
`GET`/`PUT /v1/config`, plus UI language. No workspace picker in v1.

## Requirements

```text
pip install ./kernel
pip install ./local_server
```

On first run the game gates until **both** are ready:

1. **Provider** — non-empty `model` and an API key saved (blank API key on later
   saves keeps the existing key). Prefer **Config** first when these are missing.
2. **Character** — `selected_character_id` in Assistant home config matching a
   bundled pack. Prefer **Character Select** when provider is ok but character is
   missing/invalid.

Set `AMNESIA_AGENT_PYTHON` if the game must spawn a specific Python for
`python -m amnesia_agent_local_server`.

## Run

1. Install kernel + local_server (above).
2. Open the `Assistant/` project in the Ren'Py SDK launcher (8.5+ recommended).
3. Click Launch / Run. The game spawns the local server, health-checks
   `instance_id`, loads `/v1/config` and `~/.amnesia-agent-assistant/config.json`,
   then:
   - **Both ready** → apply character (setup-or-repair; prompt injected per turn) → **Main**
   - Missing model/API key → **Config** (cannot proceed without save success)
   - Missing/invalid character → **Character Select**
   - Corrupt Assistant preferences → offer **Reset Assistant preferences**, then reload setup
   - Corrupt local-server settings → offer **Reset server settings** (clears provider credentials), then reload setup

## Architecture

```text
Assistant/game/
  api/          # HTTP JSON + SSE (Client, TurnHandle, ASSISTANT_STAGE)
  process/      # spawn / poll / shutdown local_server
  state/        # AppState + stage apply + readiness helpers
  home_config/  # ~/.amnesia-agent-assistant/config.json (selected_character_id, language)
  characters/   # bundled packs (aurora, kai)
  screens/      # loading, config, character_select, main
  script.rpy / options.rpy
```

Independent of `renpy/` — no cross-package imports. Patterns were copied slim
(including home JSON store with `chmod 0600` writes).

## Characters

Each pack lives under `game/characters/<id>/`:

| File | Role |
|---|---|
| `character.json` | id, display name, default background ID |
| `prompt.md` | frontend-owned prompt injected per turn; never written to the kernel workspace |
| `bg/` | discovered PNG/WebP background assets; filename stems are IDs |
| `expressions/` | discovered transparent PNG/WebP expression assets; filename stems are IDs |

Every pack must provide at least one background plus transparent `neutral` and `busy` expressions. PNG/WebP signatures and expression alpha channels are validated before Main; video assets are not supported in v1.

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
other local_server fields can wait). Character choice and language are persisted;
switching characters is still available from Main.
