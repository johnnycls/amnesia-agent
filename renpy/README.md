# Amnesia Agent Ren'Py frontend

This directory is a normal Ren'Py project. Open it with the Ren'Py launcher and run the game.

The project starts `amnesia-agent-local-server` as a child process and talks to it over
`127.0.0.1:8765`. The Ren'Py side deliberately uses only Python's standard-library HTTP and
SSE client; it does not import LiteLLM, FastAPI, or the kernel.

## Architecture

```text
Ren'Py game
  └─ AgentController      (game/agent_controller.py)
       └─ LocalServerClient  (game/local_server_client.py)
            └─ HTTP / SSE  →  amnesia-agent-local-server  →  amnesia-agent-kernel
```

- **`AgentController`** — Ren'Py-facing state controller. Manages chat messages,
  streaming text, workspace reads, and settings. All I/O runs on background
  threads; callbacks dispatch to the Ren'Py main thread via
  `renpy.invoke_in_main_thread()`.
- **`LocalServerClient`** — standard-library HTTP client (`urllib.request`). Starts
  the server child process, polls `/v1/health` with a 15-second timeout, streams
  turns via SSE, and verifies the server's `instance_id` on startup to detect port
  conflicts.

## Development setup

Install the server into the Python interpreter that should run beside Ren'Py:

```text
pip install ./kernel
pip install ./local_server
```

The client launches `python -m amnesia_agent_local_server` by default. Set
`AMNESIA_AGENT_PYTHON` if the server must use a specific Python executable:

```text
AMNESIA_AGENT_PYTHON=/path/to/python
```

On Windows, configure the equivalent environment variable in the shell that starts Ren'Py.

The local server owns configuration at `~/.amnesia-agent-local-server/config.json`; its kernel
workspace remains at `~/.amnesia-agent/`. The Ren'Py project currently provides functional default
screens for chat, settings, system prompt, memory, and history.

## Languages and fonts

The interface includes English, Simplified Chinese, Traditional Chinese, Japanese, and Korean.
Choose a language from **Settings > Interface language**; the selection is saved in Ren'Py's
persistent data. Model responses and workspace contents are not translated, so they can use any
language supported by the configured provider.

The project bundles `game/fonts/NotoSansCJKsc-Regular.otf` and applies it to the default Ren'Py
style. This is intentional: the default Ren'Py font does not reliably contain CJK glyphs, and
switching the interface language without a CJK-capable font produces missing-character boxes.
The font is Noto Sans CJK SC, distributed under the SIL Open Font License 1.1; the license text is
included as `game/fonts/OFL.txt`. Keep both files when redistributing the game. If you replace the
font, use one with coverage for every language you keep enabled.

## Distribution

The GitHub Actions workflow builds native Windows, macOS, and Linux distributions with Ren'Py
8.5.3. Each distribution contains a platform-native `amnesia-agent-local-server` sidecar under
`game/server` (built with `scripts/build-sidecar.py`); the client automatically prefers that
executable when it is present. The `AMNESIA_AGENT_PYTHON` override and
`python -m amnesia_agent_local_server` fallback remain available for local development.

The server is intentionally loopback-only and executes the kernel's unrestricted bash tool, so
both the packaged game and the development setup should only be run on a trusted desktop.

## Troubleshooting

**Server won't start** — Ensure `amnesia-agent-local-server` is installed in the Python
interpreter Ren'Py uses. Set `AMNESIA_AGENT_PYTHON` to point to the correct executable.

**Port conflict** — The server binds to `127.0.0.1:8765` by default. If another process is
using that port, stop it or change the server's `--port` flag (requires editing the
`LocalServerClient` startup arguments).

**Missing characters (boxes)** — The bundled CJK font covers all five interface languages. If
you replaced it, ensure the replacement has coverage for every enabled language.

**Health check timeout** — The client polls `/v1/health` for up to 15 seconds. If the server
takes longer to start (e.g. first-run pip installs), increase the timeout or pre-install
dependencies.
