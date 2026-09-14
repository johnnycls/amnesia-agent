import asyncio
import os
import shlex
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

from amnesia_agent_kernel.tools import execute_tool_calls, run_shell


def python_command(source: str) -> str:
    args = [sys.executable, "-c", source]
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_timeout_returns_bounded_tool_text(self) -> None:
        command = python_command("import time; print('before', flush=True); time.sleep(1)")
        result = await run_shell(command, timeout_seconds=0.05)
        self.assertIn("timed out", result)
        self.assertIn("before", result)

    async def test_output_overflow_terminates_and_marks_the_result(self) -> None:
        command = python_command("print('x' * 1000000)")
        result = await run_shell(command, max_output_bytes=1024)
        self.assertIn("output truncated at 1024 bytes", result)
        self.assertLess(len(result), 2000)

    async def test_full_output_is_returned(self) -> None:
        command = python_command("print('x' * 100)")
        result = await run_shell(command)
        self.assertIn("x" * 100, result)
        self.assertIn("exit code: 0", result)
        self.assertNotIn("...", result)

    async def test_tool_calls_run_concurrently_and_return_in_order(self) -> None:
        calls = [
            {"id": "one", "function": {"arguments": '{"command":"one"}'}},
            {"id": "two", "function": {"arguments": '{"command":"two"}'}},
        ]
        observed: list[str] = []
        all_started = asyncio.Event()

        async def fake_run(call: dict[str, object], *args: object) -> str:
            observed.append(str(call["id"]))
            if len(observed) == len(calls):
                all_started.set()
            await all_started.wait()
            return f"result-{call['id']}"

        with patch("amnesia_agent_kernel.tools.run_tool_call", new=AsyncMock(side_effect=fake_run)):
            messages = await asyncio.wait_for(execute_tool_calls(calls), timeout=1)

        self.assertEqual(set(observed), {"one", "two"})
        self.assertEqual([message["tool_call_id"] for message in messages], ["one", "two"])
        self.assertEqual([message["content"] for message in messages], ["result-one", "result-two"])


if __name__ == "__main__":
    unittest.main()
