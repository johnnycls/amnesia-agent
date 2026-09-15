# Assistant

A Ren'Py visual-novel-style frontend for `amnesia-agent`. Open this folder with the
Ren'Py launcher (separate from [`renpy/`](../renpy/)).

Flow: **start → Config (if needed) → Character Select → Main**. Always uses the
default workspace (`~/.amnesia-agent`, by omitting `workspace_path`). There is a
slim **Config** page for `model` + `api_key` via `GET`/`PUT /v1/config`. No
workspace picker in v1.

## Requirements

```text
pip install ./kernel
pip install ./local_server
```

On first run the game forces **Config** until a non-empty `model` and an API key
are saved (blank API key on later saves keeps the existing key). Set
`AMNESIA_AGENT_PYTHON` if the game must spawn a specific Python for
`python -m amnesia_agent_local_server`.

## Run

1. Install kernel + local_server (above).
2. Open the `Assistant/` project in the Ren'Py SDK launcher (8.5+ recommended).
3. Click Launch / Run. The game spawns the local server, health-checks
   `instance_id`, loads `/v1/config`, and opens Config if model/API key are
   missing; otherwise Character Select.

## Architecture

```text
Assistant/game/
  api/          # HTTP JSON + SSE (Client, TurnHandle, ASSISTANT_STAGE)
  process/      # spawn / poll / shutdown local_server
  state/        # AppState + stage apply helpers
  characters/   # bundled packs (aurora, kai)
  screens/      # loading, config, character_select, main
  script.rpy / options.rpy
```

Independent of `renpy/` — no cross-package imports. Patterns were copied slim.

## Characters

Each pack lives under `game/characters/<id>/`:

| File | Role |
|---|---|
| `character.json` | id, display name, default bg/expression, asset maps, palette notes |
| `prompt.md` | system prompt written on select via `PUT /v1/workspace/system-prompt` |
| `bg/*.png` | background ids |
| `sprites/*.png` | expression ids |

### Art direction

Color-block moe style: limited palette (3–5 groups), no lineart, two-step shadows,
extreme foreshortening / dynamic poses, ~6.5–7.5 head proportions. Bundled Aurora/Kai
sprites and backgrounds are generated illustrations matching this direction (not PIL solids).


## Main behaviour

- Layers: background, character sprite, message text, choice buttons, input.
- Input always visible; **Send** when idle, **Cancel** when busy.
- While `app.busy`, Main shows the character's **`busy`** sprite (UI-only). The LLM
  still emits `expression` among `neutral` / `smile` / `think` only.
- **Reset** (Main / Character Select): Confirm → `POST /v1/workspace/create-or-reset`
  on the default workspace (hard wipe), re-PUT the current character `prompt.md`,
  clear message/choices, restore default bg/expression.
- Cancel closes the SSE connection; busy clears on complete (same contract as renpy).
- `POST /v1/turn` with `response_format` `assistant_stage`:
  `message`, `choices`, `bg`, `expression`.
- Unknown `bg` / `expression` ids keep the previous stage and set a status warning.
- **Config** (Main / Character Select): `model` (required) + `api_key` (required
  until set; blank keep-existing thereafter). Turns and character play are blocked
  until both are configured.
- Quit blocked while busy; otherwise `POST /v1/shutdown` then exit.

## Tests

Unit tests do not need Ren'Py:

```text
cd Assistant && python -m unittest discover -t . -s tests -v
```

## v1 non-goals

No STT, TTS, Live2D, character editor, voice, or workspace picker. Config is
model + api_key only (other local_server fields can wait).
