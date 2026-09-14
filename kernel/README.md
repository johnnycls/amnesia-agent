# amnesia-agent-kernel

The frontend-agnostic kernel for the amnesia agent.

**Python >=3.10**

## Install

```text
pip install ./kernel
```

## API

```python
from amnesia_agent_kernel import ExecutionPolicy, KernelSession, ProviderConfig

provider = ProviderConfig(
    model="openai/example",
    api_key=None,
    base_url=None,
    provider_params=None,
)
policy = ExecutionPolicy(
    max_context_message_chars=1000,
)
session = KernelSession(provider, policy, workspace_root=None)
```

`ProviderConfig` contains only LiteLLM/provider settings. `provider_params` is an
optional mapping passed through to LiteLLM without scalar or reserved-key
filtering; kernel-controlled request fields (`model`, turn kwargs, `api_key`,
`api_base`) still win when building a request.

`ExecutionPolicy` contains kernel execution and context limits. Its defaults are:

- 1800-second command timeout
- 256 KiB combined command output
- 1000 characters for non-user context messages

These are guardrails for trusted-local execution, not a sandbox. The shell tool
still has host filesystem, network, and process access. Use a container or VM when
the model or provider is not trusted.

## Turns and streaming

`KernelSession.turn(text, response_format=None)` returns an async iterator of
`str | AllMessageValues`:

- `str` — a streamed assistant text delta.
- `AllMessageValues` — a complete assistant message (`role="assistant"`, may
  include `tool_calls`) or a tool-result message (`role="tool"`). Distinguish by
  `role`.

`response_format` is an optional JSON object passed to LiteLLM for providers that
support structured outputs. For example:

```python
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    },
}

from contextlib import aclosing

async with aclosing(session.turn("Answer this", response_format=response_format)) as events:
    async for event in events:
        if isinstance(event, str):
            ...  # streamed delta
        elif event["role"] == "assistant":
            ...  # complete assistant message; JSON text is in event["content"]
        elif event["role"] == "tool":
            ...  # tool result
```

The kernel validates that the format contains only JSON-compatible values and
makes a defensive copy before sending it to the provider. The structured result
is still exposed as the model's JSON text in the assistant message `content`;
the frontend can parse it with `json.loads` after receiving the complete message.
Provider support for a particular structured-output format varies by model.

Only one `KernelSession.turn` may be open at a time. Callers **must** wrap
iteration in `contextlib.aclosing` (or call `aclose`) so the turn slot is
released. Starting a second turn while a previous turn generator is still open
raises `RuntimeError` immediately (fail loud). Tool commands within a turn are
executed concurrently. Command timeout and output-limit failures are returned as
tool-result text so the model can recover. The process group is terminated on
timeout, output overflow, or cancel during tool execution.

History stores role messages only. Provider failures append a user message such as
`error: ProviderError: ...` and then raise. Prior daily history is not
auto-replayed into the model context; only the current turn's messages are.

### Cancel / aclose (three phases)

Cancelling the turn task (`asyncio.CancelledError`) or closing the turn async
generator (`aclose` / `contextlib.aclosing`) is phase-dependent. In all phases,
partial assistant text (when present) and a user message `user interrupted` are
persisted best-effort, then the cancel is re-raised.

| Phase | What runs | Guaranteed locally | Best-effort / not guaranteed |
|---|---|---|---|
| **Pre-stream** | awaiting `acompletion` | interrupt marker when persist succeeds | in-flight provider HTTP may still complete or bill |
| **Streaming** | iterating LiteLLM response | local consumption stops; `CustomStreamWrapper.aclose()` when present | upstream may still generate/bill tokens |
| **Tools** | `execute_tool_calls` / shell | tool tasks cancelled; shell process group terminated (SIGKILL / `taskkill`) | earlier-phase provider billing unaffected |

Upstream billing may continue after local cancel — the kernel does not claim a
hard provider abort.

## Workspace operations

The workspace implementation is internal to the kernel (`amnesia_agent_kernel.workspace`).
Controlled read/update operations are available through `KernelSession`; callers do
not construct or receive a Workspace object from the public API.

`KernelSession.__init__` always runs a lightweight setup (create the workspace
directory and empty `system_prompt.md` / `memory.md` when missing; existing
content is preserved). No seed content ships with the package.

For frontend open flows that need an explicit check before constructing a session,
use the three `@staticmethod`s (usable without a session instance; `root=None`
resolves to `~/.amnesia-agent`):

1. `KernelSession.check_workspace(root=None) -> bool` — `True` only when `root`
   exists as a directory and both `system_prompt.md` and `memory.md` exist as
   files (content may be empty). `history/` may be missing. Does **not** validate
   history JSONL contents. Returns `False` for missing/invalid structure (offer
   repair vs reset); does not raise for normal not-ok cases.
2. `KernelSession.setup_or_repair_workspace(root=None) -> None` — mkdir parents;
   create empty prompt/memory files if missing. Does **not** wipe existing content
   and does **not** delete `history/`.
3. `KernelSession.create_or_reset_workspace(root=None) -> None` — if `root` exists
   and is a directory, `shutil.rmtree` it; if missing, treat as clear; if it
   exists and is not a directory, raise `WorkspaceError`; then run setup/repair
   to recreate empty prompt/memory files.

Suggested frontend flow: **open → `check_workspace`; if ok, construct
`KernelSession`; if not, let the user choose repair (`setup_or_repair_workspace`)
or reset (`create_or_reset_workspace`)**, then open. Init setup remains
idempotent after repair/reset.

When both the system prompt and memory are empty, the system message is omitted
from the provider request. Non-empty values are joined with `\n\n`.

```python
# Strict open flow
root = None  # or a path; None → ~/.amnesia-agent
if not KernelSession.check_workspace(root):
    # Frontend: offer repair vs reset
    KernelSession.setup_or_repair_workspace(root)
    # or: KernelSession.create_or_reset_workspace(root)

session = KernelSession(provider, policy, workspace_root=root)

session.read_system_prompt()
session.update_system_prompt(text)

session.read_memory()
session.update_memory(text)

session.list_history()                 # newest ISO dates first
session.read_history()                 # newest daily history
session.read_history("2026-08-28")    # one UTC date
session.update_history(messages, "2026-08-28")
session.reset_history()
```

**Breaking:** `workspace_mode` / `mode` and `reset_workspace` are removed; use
`check_workspace`, `setup_or_repair_workspace`, and `create_or_reset_workspace`
instead.

`reset_system_prompt` and `reset_memory` remain removed.

History input and persisted records are validated as role messages only (`system`,
`user`, `assistant`, `tool`). Empty valid sequences remove a history file;
malformed inputs raise `WorkspaceError` without deleting it. Kind/sidecar history
events are no longer accepted.

The shell tool schema is a kernel constant. It is not copied to the workspace and
cannot be changed through workspace files.

## Suggested system prompt

Frontends may seed `system_prompt.md` with guidance such as: accomplish **all**
tasks through the shell tool; think carefully about how to use the shell (files,
scripts, APIs, editing memory and prompt files, and composing multi-step
commands). This is documentation for frontends only — the kernel does not ship a
prompt file.

## Error classes

The kernel uses typed `AgentError` subclasses for expected failures:

| Class | Cause |
|---|---|
| `ConfigError` | Invalid or missing provider/execution configuration |
| `WorkspaceError` | Filesystem or validation errors in the workspace |
| `ProviderError` | LiteLLM or upstream provider failures |
| `ToolError` | Shell execution failures that cannot be returned as tool text |

Provider and workspace failures propagate to the caller; ordinary shell failures
and bounded execution failures are returned to the model as tool-result text.

## Cross-platform notes

The shell tool handles process management differently per platform:

- **Unix** — commands run in a new session (`start_new_session=True`). Timeout
  kills the process group with `SIGKILL`.
- **Windows** — commands run in a new process group
  (`CREATE_NEW_PROCESS_GROUP`). Timeout kills the tree with
  `taskkill /T /F`.

Commands use `asyncio.create_subprocess_shell`, which invokes the platform
default shell (not necessarily bash).

## Boundary

The kernel accepts a `ProviderConfig` and `ExecutionPolicy` from a frontend and
validates them during `KernelSession` initialization, including LiteLLM provider
preflight via `validate_provider_config`. It has no dependency on frontend
configuration paths.

## Breaking changes (this refactor)

- Tool schema name renamed: `bash` → `shell` (`BASH_TOOL` → `SHELL_TOOL`,
  `run_bash` → `run_shell`).
- Turn stream no longer uses `Delta` / `AssistantMessage` / `ToolResult` /
  `Event`; yields `str | AllMessageValues` instead (`events.py` removed).
- Split internals into `provider.py`, `streaming.py`, and `workspace/` package.
- Default command timeout is **1800** seconds.
- Removed `reset_system_prompt` and `reset_memory`.
- Removed `workspace_mode` / `mode` and `reset_workspace`; use
  `KernelSession.check_workspace`, `setup_or_repair_workspace`, and
  `create_or_reset_workspace` instead.
- History is role-only; `kind` events are gone.
- Provider/cancel failures append user-role history messages then raise.
- `provider_params` is `Mapping[str, Any] | None` and is not scalar-validated.
- Message types use LiteLLM `AllMessageValues` (no `Message` alias).
