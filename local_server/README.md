# amnesia-agent-local-server

Reusable loopback HTTP boundary for `amnesia-agent-kernel`. Desktop frontends
(Electron, Ren'Py) talk HTTP only; this package owns persistent config and one
session lifecycle.

**Python >=3.10**

## Roles

| Layer | Responsibility |
|---|---|
| Kernel | Atomic capabilities (`KernelSession`) |
| local_server | Loopback HTTP + `~/.amnesia-agent-local-server/config.json` + per-turn sessions |
| Frontend | HTTP client only |

## Development

```text
pip install ./kernel
pip install ./local_server
amnesia-agent-local-server
```

Binds to `127.0.0.1:8765` by default:

```text
amnesia-agent-local-server --host 127.0.0.1 --port 8765
```

This server exposes the kernel's unrestricted local shell tool. Keep it on
loopback and run it only on a trusted machine.

## Package layout

```text
amnesia_agent_local_server/
├── config.py       # defaults constants + ConfigStore persistence
├── session.py      # SessionManager: fresh KernelSession per turn, turn busy flag
├── sse.py          # str | AllMessageValues → SSE envelopes (fail-loud)
├── routes/         # thin routers: health, config, workspace, turn, shutdown
├── app.py          # FastAPI assembly + exception → HTTP JSON mapping
└── __main__.py     # CLI entry (loopback bind; wires uvicorn for /shutdown)
```

## Configuration

Defaults live as importable Python constants in `amnesia_agent_local_server.config`
(`DEFAULT_MODEL`, `DEFAULT_COMMAND_TIMEOUT_SECONDS`, `DEFAULT_WORKSPACE_PATH`, …
/ `default_config_dict()`). They are persisted at
`~/.amnesia-agent-local-server/config.json` (separate from the kernel workspace).

Provider/policy fields align with the CLI. **local_server-only:** `workspace_path`
(string; empty/missing → kernel default `~/.amnesia-agent`).

- Missing file: lazy-created from those constants.
- Corrupt/invalid config: fail loud with an HTTP error — **not** auto-repaired.
- Restore defaults only via `POST /v1/config/reset` (rewrites from constants).

Public responses mask the API key: `api_key` is always `null` and
`api_key_set: boolean` indicates whether a key is stored. `workspace_path` is
returned as configured (empty string means kernel default).

## HTTP API (`/v1`)

Path/method names follow `KernelSession` (kebab-case for multi-word methods).
There is no parallel synonym vocabulary. `/v1` is applied once at app include
time; workspace/config routers own their `/workspace` and `/config` prefixes.

### Health

```text
GET /v1/health
→ {"status":"ok","active_turn":false,"api_version":"v1","instance_id":"..."}
```

`instance_id` is a random UUID set at startup so frontends can detect stale
servers on a contested port.

### Configuration

```text
GET  /v1/config           → public config (api_key masked)
PUT  /v1/config           → partial update (any subset of keys)
POST /v1/config/reset     → rewrite defaults from constants
```

Config changes return **409** while a turn is active. There is no long-lived
`KernelSession` cache: every turn and workspace read/update builds a fresh
session from the latest config (including `workspace_path`).

### Turn (SSE)

```text
POST /v1/turn   {"text":"...","response_format":{...}|null}
```

Body: required `text` (non-empty string); optional `response_format` (JSON object
or `null` / omitted). Wrong types fail loud with **422**. When omitted or
`null`, the server passes `None` to `KernelSession.turn` (no structured output).
When provided, the object is forwarded unchanged to the kernel.

Server-Sent Events stream. Kernel `turn` yields `str` deltas and role messages
(`AllMessageValues`); the server maps them as:

```text
data: {"type":"delta","data":{"text":"..."}}
data: {"type":"assistant","data":{"content":"...","tool_calls":[],"structured":true,"answer":"...","choices":[...]}}
data: {"type":"assistant","data":{"content":"...","tool_calls":[...]}}
data: {"type":"tool_result","data":{"content":"..."}}
data: {"type":"done","data":{}}
data: {"type":"error","data":{"error_type":"...","message":"..."}}
```

- **All** assistant role messages use `type: "assistant"` with `tool_calls` in
  `data` (empty list when the model did not call tools). There is **no** separate
  `type: "tool_call"` envelope (breaking change for clients that switched on
  that type — inspect `data.tool_calls` instead). `tool_result` remains for
  `role=tool`.
- `assistant` events parse structured JSON (`answer` / `choices`) when content
  matches a schema the client requested and there are no tool calls; otherwise
  `structured` is false / omitted for tool-calling assistants.
- Malformed assistant/tool content (non-string content, non-list `tool_calls`)
  and unknown kernel event shapes fail loud as an `error` envelope
  (`ServerError`).
- **409** if a turn is already active (one at a time).
- Cancel an in-progress turn **only** by disconnecting the SSE stream — there is
  no explicit cancel endpoint.
- On disconnect, the server `aclose`s the turn generator chain through
  `KernelSession.turn` → `agent_turn` → LiteLLM `CustomStreamWrapper.aclose()`
  when present, releases the busy flag, and releases the kernel turn lock.
  That is **best-effort**: local streaming stops and the HTTP connection to the
  provider is asked to close, but providers may still finish generating or bill
  tokens. There is no hard guarantee of immediate upstream abort.
- The server does **not** auto-apply a structured-output schema. Clients that
  want choice chips (Electron / Ren'Py) must send `response_format` themselves.
  Example schema to copy:

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "answer_with_choices",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "answer": {"type": "string"},
        "choices": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["answer", "choices"],
      "additionalProperties": false
    }
  }
}
```

### Workspace

Mirrors `KernelSession` staticmethods and read/update APIs. Paths operate on the
**configured** `workspace_path` (resolved: empty → kernel default
`~/.amnesia-agent`; otherwise the configured string, with expanduser in the
kernel). Invalid roots fail loud as `WorkspaceError` → HTTP **400**.

```text
GET  /v1/workspace/check                → {"ok": true|false}
POST /v1/workspace/setup-or-repair      → create missing dir / empty prompt+memory
POST /v1/workspace/create-or-reset      → wipe workspace root, recreate empty files

GET  /v1/workspace/system-prompt        → {"content":"..."}
PUT  /v1/workspace/system-prompt        → {"content":"..."}

GET  /v1/workspace/memory               → {"content":"..."}
PUT  /v1/workspace/memory               → {"content":"..."}

GET  /v1/workspace/history              → {"dates":[...]}   # newest first
GET  /v1/workspace/history/{YYYY-MM-DD} → {"date":"...","messages":[...]}
PUT  /v1/workspace/history              → {"messages":[...],"date":...|null}
POST /v1/workspace/history/reset        → {"reset": true}
```

`PUT /v1/workspace/history` mirrors `KernelSession.update_history(messages, date)`:
optional `date` defaults to today when omitted/null.

Suggested open flow: **check → if not ok, setup-or-repair or create-or-reset →
then read/update / turn**. While a turn is active, **all workspace writes**
return **409** via `require_idle`: `update_system_prompt`, `update_memory`,
`update_history`, history reset, setup/repair, create/reset, and config changes.
Reads stay allowed. Changing `workspace_path` does not need a special session
invalidate (sessions are not cached across turns).

### Shutdown

```text
POST /v1/shutdown  → {"shutting_down": true}
```

Available only when the process was started via the official
`amnesia-agent-local-server` / `__main__` entrypoint (which wires
`app.state.uvicorn_server`). Otherwise the endpoint returns **503** with a JSON
`detail` — it does **not** pretend to shut down.

On success it best-effort cancels any in-flight turn (same `aclose` chain as SSE
disconnect) and sets uvicorn `should_exit` so the process can exit instead of
waiting forever on an open LLM stream. Kept for desktop frontends that spawn the
process.

## Error handling

Expected failures are mapped to HTTP responses with status codes and JSON bodies
of the form `{"detail": "..."}` (optional `path` for config/workspace errors).
They do **not** escape as bare ASGI exceptions.

| Condition | Status |
|---|---|
| Request body validation | 422 |
| Turn already active / mutate during turn | 409 |
| Shutdown without official entrypoint | 503 |
| `ConfigError` / `WorkspaceError` / `AgentError` / `ValueError` / `OSError` | 400 |

Turn-time kernel errors are delivered as SSE `error` envelopes, not as HTTP
error statuses on the streaming response (the stream already started with 200).

## Breaking changes (rewrite)

Relative to the pre-rewrite `service.py` / monolithic `app.py` layout:

1. **Internal package layout** — `service.py` and `protocol.py` are gone;
   use `session.py`, `sse.py`, and `routes/*`. Public Python exports are
   `create_app`, `ConfigStore`, `LoadedConfig`, `SessionManager`.
2. **`PUT /v1/workspace/history`** — new endpoint mirroring
   `KernelSession.update_history`.
3. **Error boundary** — expected failures always return HTTP JSON (`detail`);
   clients must not rely on unhandled 500s for validation / busy / config /
   workspace errors.
4. **Still removed (from earlier kernel alignment)** —
   `POST /v1/workspace/system-prompt/reset` and
   `POST /v1/workspace/memory/reset` do not exist; use setup/repair or
   create/reset.
5. **Config defaults** — no packaged `data/config.json`; defaults are Python
   constants. `/shutdown` is honest when uvicorn is not wired (503).
6. **`workspace_path`** — local_server config field (empty = kernel default).
   Workspace HTTP and turns use the configured path. Sessions are not cached
   across turns (fresh `KernelSession` each time from latest config).
7. **`POST /v1/turn` `response_format`** — optional client-supplied structured
   output. The server no longer always requests `answer_with_choices`. Clients
   that relied on server-side structured output must send `response_format`
   themselves (see Turn section example).

**Frontends (Electron, Ren'Py) must follow these HTTP changes.** Soft prompt /
memory reset URLs and any assumption that history cannot be updated over HTTP
are obsolete. Clients that previously assumed every turn used
`answer_with_choices` must now pass that schema (or another) as
`response_format`.

8. **SSE assistant envelope** — assistant messages with `tool_calls` are always
   `type: "assistant"` (no `type: "tool_call"`). Clients must branch on
   `data.tool_calls`.
9. **Idle write policy** — mid-turn `PUT` system-prompt / memory / history returns
   **409** (same as config and lifecycle writes).
10. **Default `command_timeout_seconds`** — **1800** (aligned with kernel `ExecutionPolicy`).


## Troubleshooting

**409 on `/v1/turn`** — A turn is already active. Wait for it to finish or close
the SSE connection to cancel.

**409 on config / workspace lifecycle** — Finish or cancel the active turn first.

**Corrupt config** — Fix or delete `~/.amnesia-agent-local-server/config.json`,
or call `POST /v1/config/reset`. The server will not silently rewrite a bad file.

**503 on `/v1/shutdown`** — The ASGI app was created without the official
entrypoint wiring (`uvicorn_server` is unset), e.g. under a test client or a
custom host. Start via `amnesia-agent-local-server` for shutdown support.
