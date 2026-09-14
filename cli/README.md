# amnesia-agent-cli

Minimal terminal CLI and configuration store for `amnesia-agent-kernel`.

**Python >=3.10**

## Install

```text
pip install ./kernel
pip install ./cli
amnesia-agent
```

## Usage

```text
amnesia-agent          # start interactive REPL
amnesia-agent --version
amnesia-agent --help
```

On first run the CLI creates a config file at `~/.amnesia-agent-cli/config.json`.
If the configuration is invalid or missing required fields, the CLI opens the file
in your platform's default editor.

## Configuration

`ConfigStore` owns the user-editable file at:

```text
~/.amnesia-agent-cli/config.json
```

This is separate from the kernel workspace at `~/.amnesia-agent/`. The store
seeds missing configuration and validates JSON values, returning a `LoadedConfig`
containing a `ProviderConfig` and `ExecutionPolicy`.

### Config keys

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | string | `""` | LiteLLM model identifier (e.g. `openai/gpt-4o`) |
| `api_key` | string | `""` | API key for the provider |
| `base_url` | string | `""` | Optional custom base URL |
| `provider_params` | object | `{}` | Extra provider-specific parameters |
| `command_timeout_seconds` | float | `1800` | Shell command timeout |
| `max_command_output_bytes` | int | `262144` | Max combined output per command (256 KiB) |
| `max_context_message_chars` | int | `1000` | Max chars for non-user context messages |

Example:

```json
{
  "model": "openai/gpt-4o",
  "api_key": "sk-...",
  "base_url": "",
  "provider_params": {},
  "command_timeout_seconds": 1800,
  "max_command_output_bytes": 262144,
  "max_context_message_chars": 1000
}
```

Invalid configuration errors include the config path so the CLI can open the file
with the platform's default editor. `ConfigStore.reset()` restores the packaged
blank/default configuration.

## CLI behavior

The CLI creates one `ConfigStore`. Before every user turn it reloads the
configuration and constructs a fresh kernel `KernelSession` from that snapshot.
Session initialization performs provider preflight; typed initialization or turn
failures are logged and terminate the process. The session creates the default
kernel workspace internally. The CLI renders kernel events as terminal output.

### Terminal rendering

- **Streaming text** is displayed in bold.
- **Tool output** (bash results) is displayed dimmed, with the exit code colored
  green (0) or red (non-zero). At most 4 lines of output are shown; the full
  output is available in the kernel workspace.
- On Windows, the CLI enables VT processing for ANSI escape support.

Reset operations are exposed through the Python APIs, not as destructive CLI
commands.
