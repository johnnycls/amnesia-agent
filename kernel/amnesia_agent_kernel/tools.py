"""Bounded shell execution and tool-call dispatch."""

import asyncio
import json
import logging
import math
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

from litellm.types.llms.openai import AllMessageValues

from amnesia_agent_kernel.errors import ToolError

logger = logging.getLogger(__name__)

SHELL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": (
            "Run a shell command via the platform default shell "
            "(asyncio.create_subprocess_shell; not necessarily bash) and return its "
            "exit code plus combined stdout/stderr as plain text. All agent work should "
            "go through this tool: compose commands thoughtfully for file operations, "
            "scripts, API calls, editing memory/prompt files, and other tasks. Commands "
            "have a session timeout and bounded output."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                }
            },
            "required": ["command"],
        },
    },
}


def _process_options() -> dict[str, Any]:
    """Return subprocess options that start an independent process group."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    if sys.platform.startswith(("linux", "darwin", "freebsd", "openbsd", "netbsd", "aix")):
        return {"start_new_session": True}
    raise ToolError(f"Unsupported process-group platform: {sys.platform}", tool="shell")


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate the shell and all descendants started for the command."""
    if proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(proc.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
            if proc.returncode is None:
                proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except (OSError, TypeError, ValueError) as e:
        raise ToolError(f"Could not terminate shell process: {e}", tool="shell") from e
    try:
        await proc.wait()
    except (OSError, TypeError, ValueError) as e:
        raise ToolError(f"Could not wait for shell process: {e}", tool="shell") from e


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Signal the shell process group to exit without waiting for reaping."""
    if proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(proc.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
            if proc.returncode is None:
                proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except (OSError, TypeError, ValueError) as e:
        raise ToolError(f"Could not terminate shell process: {e}", tool="shell") from e


class _OutputCollector:
    """Keep a bounded combined byte prefix from two output streams."""

    def __init__(self, limit: int, timeout_seconds: float) -> None:
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.used = 0
        self.overflowed = False
        self._lock = asyncio.Lock()
        self._streams: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}

    async def add(self, stream_name: str, chunk: bytes) -> bool:
        async with self._lock:
            remaining = self.limit - self.used
            if remaining <= 0:
                self.overflowed = True
                return True
            accepted = chunk[:remaining]
            self._streams[stream_name].extend(accepted)
            self.used += len(accepted)
            if len(accepted) < len(chunk):
                self.overflowed = True
            return self.overflowed

    def snapshot(self) -> tuple[bytes, bytes]:
        return bytes(self._streams["stdout"]), bytes(self._streams["stderr"])


async def _read_output(
    stream: asyncio.StreamReader,
    stream_name: str,
    collector: _OutputCollector,
) -> bool:
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return False
        if await collector.add(stream_name, chunk):
            return True


async def _collect_output(
    proc: asyncio.subprocess.Process,
    collector: _OutputCollector,
) -> None:
    if proc.stdout is None or proc.stderr is None:
        raise ToolError("Shell process did not provide output pipes", tool="shell")
    readers = {
        asyncio.create_task(_read_output(proc.stdout, "stdout", collector)),
        asyncio.create_task(_read_output(proc.stderr, "stderr", collector)),
    }
    waiter = asyncio.create_task(proc.wait())
    pending: set[asyncio.Task[Any]] = set(readers)
    pending.add(waiter)
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is waiter:
                    task.result()
                elif task.result():
                    # Kill and cancel the concurrent waiter/readers. A second
                    # Process.wait() can deadlock while pipe buffers are full;
                    # run_shell reaps via communicate() afterward.
                    await _kill_process_group(proc)
                    for pending_task in readers | {waiter}:
                        pending_task.cancel()
                    await asyncio.gather(*readers, waiter, return_exceptions=True)
                    return
    except asyncio.CancelledError:
        try:
            await _terminate_process(proc)
        finally:
            for task in readers | {waiter}:
                task.cancel()
            await asyncio.gather(*readers, waiter, return_exceptions=True)
        raise
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def _close_pipes(proc: asyncio.subprocess.Process) -> None:
    """Drain/close asyncio subprocess transports after manual stream reads."""
    try:
        await proc.communicate()
    except (OSError, RuntimeError, ValueError):
        logger.debug("Could not close shell output pipes cleanly", exc_info=True)


def _format_output(
    proc: asyncio.subprocess.Process,
    collector: _OutputCollector,
    timed_out: bool,
) -> str:
    stdout, stderr = collector.snapshot()
    output = (stdout + stderr).decode("utf-8", "replace").strip() or "(no output)"
    status = proc.returncode
    suffix = ""
    if timed_out:
        suffix = f"\n[command timed out after {collector.timeout_seconds:g} seconds]"
    elif collector.overflowed:
        suffix = f"\n[output truncated at {collector.limit} bytes; process terminated]"
    return f"exit code: {status}\noutput: {output}{suffix}"


async def run_shell(
    command: str,
    timeout_seconds: float = 1800.0,
    max_output_bytes: int = 256 * 1024,
) -> str:
    """Run a shell command with timeout and combined-output limits."""
    if not isinstance(command, str) or not command:
        raise ToolError("shell command must be a non-empty string", tool="shell")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes <= 0
    ):
        raise ToolError("shell execution limits must be positive", tool="shell", command=command)
    try:
        options = _process_options()
        proc: asyncio.subprocess.Process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **options,
        )
    except ToolError:
        raise
    except (OSError, TypeError, ValueError) as e:
        raise ToolError(f"Could not start shell command: {e}", tool="shell", command=command) from e

    collector = _OutputCollector(max_output_bytes, timeout_seconds)
    try:
        await asyncio.wait_for(_collect_output(proc, collector), timeout_seconds)
    except asyncio.TimeoutError:
        try:
            await _terminate_process(proc)
        except ToolError:
            logger.error("Shell process cleanup failed after timeout", exc_info=True)
        await _close_pipes(proc)
        return _format_output(proc, collector, timed_out=True)
    except ToolError:
        raise
    except Exception as e:
        try:
            await _terminate_process(proc)
        except ToolError:
            logger.error("Shell process cleanup failed after collection error", exc_info=True)
        raise ToolError(
            f"Could not collect shell output: {type(e).__name__}: {e}",
            tool="shell",
            command=command,
        ) from e
    await _close_pipes(proc)
    return _format_output(proc, collector, timed_out=False)


def _parse_command(raw_arguments: str) -> str:
    """Extract the 'command' string from a tool-call arguments JSON blob."""
    arguments: Any = json.loads(raw_arguments)
    if not isinstance(arguments, dict):
        raise TypeError("tool arguments must be a JSON object")
    command: Any = arguments["command"]
    if not isinstance(command, str) or not command:
        raise TypeError("'command' must be a non-empty string")
    return command


def _tool_error_text(error: Exception) -> str:
    return f"error: {type(error).__name__}: {error}"


async def run_tool_call(
    call: dict[str, Any],
    timeout_seconds: float = 1800.0,
    max_output_bytes: int = 256 * 1024,
) -> str:
    """Parse a tool call and run its shell command, returning result text."""
    try:
        if not isinstance(call, dict):
            raise ToolError("tool call must be an object", tool="shell")
        function = call.get("function", {})
        if not isinstance(function, dict) or function.get("name") != "shell":
            raise ToolError("unknown tool; expected 'shell'", tool="shell")
        command = _parse_command(function.get("arguments", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ToolError) as e:
        return _tool_error_text(e)
    try:
        return await run_shell(command, timeout_seconds, max_output_bytes)
    except ToolError as e:
        return _tool_error_text(e)


def _tool_message(call: dict[str, Any], content: str) -> AllMessageValues:
    """Build a tool-result message matching the given tool call."""
    call_id = call.get("id") if isinstance(call, dict) else None
    if not isinstance(call_id, str) or not call_id:
        raise ToolError("tool call had no valid ID", tool="shell")
    return {"role": "tool", "tool_call_id": call_id, "content": content}


async def execute_tool_calls(
    tool_calls: Sequence[dict[str, Any]],
    timeout_seconds: float = 1800.0,
    max_output_bytes: int = 256 * 1024,
) -> list[AllMessageValues]:
    """Execute all calls concurrently and return results in call order."""
    tasks = [
        asyncio.create_task(run_tool_call(call, timeout_seconds, max_output_bytes))
        for call in tool_calls
    ]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return [_tool_message(call, result) for call, result in zip(tool_calls, results, strict=True)]
