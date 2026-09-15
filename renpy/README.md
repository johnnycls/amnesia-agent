# Amnesia Agent Ren'Py frontend

This directory is a normal Ren'Py project. Open it with the Ren'Py launcher and run the game.

The project starts `amnesia-agent-local-server` as a child process and talks to it over
`127.0.0.1:8765`. The Ren'Py side uses only Python's standard-library HTTP and SSE client; it
does not import LiteLLM, FastAPI, or the kernel.

## Architecture

```text
renpy/game/
  api/        # HTTP JSON + SSE client (Client, TurnHandle, ANSWER_WITH_CHOICES)
  home_config/ # ~/.amnesia-agent-renpy/config.json store
  process/    # spawn / poll / shutdown local_server (sidecar or python -m)
  state/      # AppState: pages, busy, workspace, last assistant, forms
  defaults/   # packaged default system prompt string
  screens/    # loading, workspace_select, main, workspace_settings, history, config
  script.rpy / options.rpy / translations.rpy / fonts/
```

`game/server/` is reserved for the **CI-built native sidecar executable** (gitignored). Process
lifecycle code lives in `process/` so it does not collide with that directory.

## Pages / flow

1. **Loading** — load Ren'Py config (fail loud if corrupt); spawn local_server; poll `/v1/health`.
2. **Workspace Select** — recent list (open / delete); Import and Create use an OS
   folder picker (no free-text path).
   - Import: pick folder → `GET /v1/workspace/check` → if valid `setup-or-repair`; if not,
     choose setup-or-repair or create-or-reset (hard wipe).
   - Create: pick folder → Confirm → `POST /v1/workspace/create` (empty-only; errors if non-empty).
   - On success: bump `recent_workspaces[].last_opened_at`, persist Ren'Py config, enter Main.
3. **Auto-enter Main** when `recent_workspaces[0]` exists and check passes (then setup-or-repair).
4. **Main** — Back; Workspace Settings; History; Config. Shows **only the last assistant
   message**. Choice buttons when present. Input disabled while busy. `POST /v1/turn` with
   `workspace_path` and default `answer_with_choices` `response_format`. Cancel disconnects SSE.
5. **Workspace Settings** — system prompt / memory read+update. Reset prompt writes the
   **packaged Ren'Py default string** (not a server create-or-reset endpoint). No history here.
6. **History** — list dates, read one day as `role: msg time` lines, delete one day via
   `PUT /v1/workspace/history` with empty `messages` (removes that day's JSONL), clear all via
   `POST /v1/workspace/history/reset`. Always pass `workspace_path`.
7. **Config** — single form. Save routes:
   - local_server fields → `PUT /v1/config`
   - Ren'Py `language` → home JSON (`recent_workspaces` managed on Workspace Select)
   - Reset local server → `POST /v1/config/reset`
   - Reset Ren'Py → rewrite home JSON defaults (`language=english`, `recent_workspaces=[]`)
8. **Quit** — blocked while busy; when idle: `POST /v1/shutdown` then exit.

## Ren'Py config schema

Path: `~/.amnesia-agent-renpy/config.json`

```json
{
  "language": "english",
  "recent_workspaces": [
    {"path": "/absolute/or/~/path", "last_opened_at": "2026-09-15T12:00:00+00:00"}
  ]
}
```

- `language`: `english` | `schinese` | `tchinese` | `japanese` | `korean`
- `recent_workspaces`: sorted descending by `last_opened_at` (no separate `last_workspace`)
- Missing file → lazy defaults. Corrupt / unexpected keys → fail loud (no silent repair).

## Development setup

```text
pip install ./kernel
pip install ./local_server
```

The client launches `python -m amnesia_agent_local_server` by default. Set
`AMNESIA_AGENT_PYTHON` if the server must use a specific Python executable.

Local server config remains at `~/.amnesia-agent-local-server/config.json`. Workspace roots are
chosen per open (default kernel path is still `~/.amnesia-agent` when omitted on the server).

## Languages and fonts

English, Simplified Chinese, Traditional Chinese, Japanese, and Korean. Language is stored in
the Ren'Py home JSON (Config page). Model responses and workspace contents are not translated.

The project bundles `game/fonts/NotoSansCJKsc-Regular.otf` (SIL OFL 1.1; see `game/fonts/OFL.txt`)
and applies it as the default style font so CJK glyphs render.

## Distribution

GitHub Actions builds Windows / macOS / Linux distributions with Ren'Py 8.5.3. Each ship a
platform-native `amnesia-agent-local-server` under `game/server` via `scripts/build-sidecar.py`.
The client prefers that executable when present; `AMNESIA_AGENT_PYTHON` / `python -m` remain for
local development.

The server is loopback-only and runs the kernel's unrestricted bash tool — use only on a trusted
desktop.

## Troubleshooting

**Server won't start** — Install `amnesia-agent-local-server` for the Python Ren'Py uses, or set
`AMNESIA_AGENT_PYTHON`.

**Port conflict** — Default `127.0.0.1:8765`. Another process on that port fails loud via
`instance_id` mismatch.

**Corrupt Ren'Py config** — Fix or delete `~/.amnesia-agent-renpy/config.json`, or use
**Reset Ren'Py settings** on the Config page.

**Health timeout** — Client polls `/v1/health` up to 15 seconds after spawn.
