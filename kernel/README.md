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

These are guardrails for trusted-local execution, not a sandbox. The bash tool
still has host filesystem, network, and process access. Use a container or VM when
the model or provider is not trusted.

## Turns and events

`KernelSession.turn(text, response_format=None)` returns an async iterator of:

- `Delta` — streamed assistant text.
- `AssistantMessage` — a complete assistant response, including tool calls.
- `ToolResult` — one result per executed bash call.

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

async for event in session.turn("Answer this", response_format=response_format):
    ...
```

The kernel validates that the format contains only JSON-compatible values and
makes a defensive copy before sending it to the provider. The structured result
is still exposed as the model's JSON text in `AssistantMessage.message["content"]`;
the frontend can parse it with `json.loads` after receiving the complete message.
Provider support for a particular structured-output format varies by model.

Concurrent turns on one session are queued and serialized. Tool commands are
executed concurrently. Command timeout and output-limit failures are returned as
tool-result text so the model can recover.
The process group is terminated on timeout or output overflow.

History stores role messages only. Provider failures append a user message such as
`error: ProviderError: ...` and then raise. Cancellation re-raises
`asyncio.CancelledError` after persisting partial assistant text (when present)
and a user message `user interrupted` when possible. Prior daily history is not
auto-replayed into the model context; only the current turn's messages are.

## Workspace operations

The workspace implementation is internal to the kernel (`amnesia_agent_kernel.workspace`).
Controlled read/update operations are available through `KernelSession`; callers do
not construct or receive a Workspace object from the public API.

On setup, the kernel creates the workspace directory and empty `system_prompt.md` /
`memory.md` files when they are missing. There are no packaged seed prompts.

When both the system prompt and memory are empty, the system message is omitted
from the provider request. Non-empty values are joined with `\n\n`.

```python
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

`reset_system_prompt`, `reset_memory`, and `reset_workspace` have been removed.

History input and persisted records are validated as role messages only (`system`,
`user`, `assistant`, `tool`). Empty valid sequences remove a history file;
malformed inputs raise `WorkspaceError` without deleting it. Kind/sidecar history
events are no longer accepted.

The bash tool schema is a kernel constant. It is not copied to the workspace and
cannot be changed through workspace files.

## Error classes

The kernel uses typed `AgentError` subclasses for expected failures:

| Class | Cause |
|---|---|
| `ConfigError` | Invalid or missing provider/execution configuration |
| `WorkspaceError` | Filesystem or validation errors in the workspace |
| `ProviderError` | LiteLLM or upstream provider failures |
| `ToolError` | Bash execution failures that cannot be returned as tool text |

Provider and workspace failures propagate to the caller; ordinary shell failures
and bounded execution failures are returned to the model as tool-result text.

## Cross-platform notes

The bash tool handles process management differently per platform:

- **Unix** — commands run in a new session (`start_new_session=True`). Timeout
  kills the process group with `SIGKILL`.
- **Windows** — commands run in a new process group
  (`CREATE_NEW_PROCESS_GROUP`). Timeout kills the tree with
  `taskkill /T /F`.

## Boundary

The kernel accepts a `ProviderConfig` and `ExecutionPolicy` from a frontend and
validates them during `KernelSession` initialization, including LiteLLM provider
preflight via `validate_provider_config`. It has no dependency on frontend
configuration paths.

## Breaking changes (this refactor)

- Split internals into `provider.py`, `streaming.py`, and `workspace/` package.
- Deleted packaged `data/` seeds; missing prompt/memory files are created empty.
- Default command timeout is **1800** seconds.
- Removed `reset_system_prompt`, `reset_memory`, and `reset_workspace`.
- History is role-only; `kind` events are gone.
- Provider/cancel failures append user-role history messages then raise.
- `provider_params` is `Mapping[str, Any] | None` and is not scalar-validated.
- Message types use LiteLLM `AllMessageValues` (no `Message` alias).
