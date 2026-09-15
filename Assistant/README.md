# Assistant

A Ren'Py visual-novel-style frontend for `amnesia-agent`. Open this folder with the
Ren'Py launcher (separate from [`renpy/`](../renpy/)).

Flow: **start → Character Select → Main**. Always uses the default workspace
(`~/.amnesia-agent`, by omitting `workspace_path`) and the default local_server
config (`~/.amnesia-agent-local-server/config.json`). No workspace picker or
settings UI in v1.

## Requirements

```text
pip install ./kernel
pip install ./local_server
```

Configure the model / API key in `~/.amnesia-agent-local-server/config.json`
(same as the other frontend). Set `AMNESIA_AGENT_PYTHON` if the game must spawn
a specific Python for `python -m amnesia_agent_local_server`.

## Run

1. Install kernel + local_server (above).
2. Open the `Assistant/` project in the Ren'Py SDK launcher (8.5+ recommended).
3. Click Launch / Run. The game spawns the local server, health-checks
   `instance_id`, then shows Character Select.

## Architecture

```text
Assistant/game/
  api/          # HTTP JSON + SSE (Client, TurnHandle, ASSISTANT_STAGE)
  process/      # spawn / poll / shutdown local_server
  state/        # AppState + stage apply helpers
  characters/   # bundled packs (aurora, kai)
  screens/      # loading, character_select, main
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

### Art direction (v1 placeholders)

Color-block moe style: limited palette (3–5 groups), no lineart, two-step shading,
clear light/dark contrast, exaggerated foreshortening. Assets are procedural
placeholders (PIL), not production illustration.

- **Aurora** — cool violet / teal / lavender skin
- **Kai** — warm auburn / forest green / amber

Palettes are documented in each `character.json` under `"palette"`.

## Main behaviour

- Layers: background, character sprite, message text, choice buttons, input.
- Input always visible; **Send** when idle, **Cancel** when busy.
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

No STT, TTS, Live2D, character editor, voice, workspace picker, or settings UI.
