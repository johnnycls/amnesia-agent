import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from amnesia_agent_kernel import (
    ConfigError,
    ExecutionPolicy,
    KernelSession,
    ProviderConfig,
    ProviderError,
    ToolError,
    WorkspaceError,
    validate_provider_config,
)
from amnesia_agent_kernel.agent import agent_turn
from amnesia_agent_kernel.tools import run_tool_call
from amnesia_agent_kernel.workspace import Workspace


class ErrorHierarchyTests(unittest.TestCase):
    def test_specific_errors_are_typed(self) -> None:
        self.assertTrue(issubclass(ConfigError, Exception))
        self.assertTrue(issubclass(ProviderError, Exception))
        self.assertTrue(issubclass(ToolError, Exception))
        self.assertTrue(issubclass(WorkspaceError, Exception))


class ProviderValidationTests(unittest.TestCase):
    def test_malformed_preflight_result_is_provider_error(self) -> None:
        config = ProviderConfig("openai/test")
        with (
            patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value=None,
            ),
            self.assertRaises(ProviderError),
        ):
            validate_provider_config(config)

    def test_noncredential_provider_params_do_not_bypass_missing_key(self) -> None:
        config = ProviderConfig("openai/test", provider_params={"temperature": 0.5})
        with (
            patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                return_value={"keys_in_environment": False, "missing_keys": ["OPENAI_API_KEY"]},
            ),
            self.assertRaises(ProviderError),
        ):
            validate_provider_config(config)

    def test_invalid_provider_params_are_rejected_before_preflight(self) -> None:
        for params, expected in (
            ([], "provider_params must be a JSON object or None"),
            (
                {"temperature": float("nan")},
                "provider_params.temperature must contain finite numbers",
            ),
            (
                {"nested": object()},
                "provider_params.nested must contain only JSON-compatible values",
            ),
        ):
            with self.subTest(params=params), patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment"
            ) as preflight:
                with self.assertRaises(ConfigError) as context:
                    validate_provider_config(ProviderConfig("openai/test", provider_params=params))  # type: ignore[arg-type]
            self.assertIn(expected, str(context.exception))
            preflight.assert_not_called()

    def test_provider_scalar_types_are_rejected_before_preflight(self) -> None:
        with patch("amnesia_agent_kernel.provider.litellm.validate_environment") as preflight:
            with self.assertRaises(ConfigError):
                validate_provider_config(ProviderConfig("openai/test", api_key=42))  # type: ignore[arg-type]
        preflight.assert_not_called()

    def test_session_preflights_before_workspace_setup(self) -> None:
        config = ProviderConfig("openai/test")
        with (
            patch(
                "amnesia_agent_kernel.provider.litellm.validate_environment",
                side_effect=RuntimeError("missing credentials"),
            ),
            self.assertRaises(ProviderError),
        ):
            KernelSession(config, workspace_root=tempfile.mkdtemp())


class ToolErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_failure_becomes_tool_result_text(self) -> None:
        call = {
            "id": "c1",
            "function": {"name": "shell", "arguments": '{"command":"echo hi"}'},
        }
        with patch(
            "amnesia_agent_kernel.tools.run_shell",
            new=AsyncMock(side_effect=ToolError("cannot start shell")),
        ):
            result = await run_tool_call(call)
        self.assertIn("error", result)
        self.assertIn("cannot start shell", result)

    async def test_unknown_tool_becomes_tool_result_text(self) -> None:
        call = {
            "id": "c1",
            "function": {"name": "python", "arguments": '{"command":"echo hi"}'},
        }
        result = await run_tool_call(call)
        self.assertIn("unknown tool", result)


class AgentTurnErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_failure_persists_partial_message_and_user_error(self) -> None:
        async def broken_stream() -> object:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="partial", tool_calls=[]))]
            )
            raise RuntimeError("connection reset")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with patch(
                "amnesia_agent_kernel.agent.acompletion",
                new=AsyncMock(return_value=broken_stream()),
            ):
                with self.assertRaises(ProviderError):
                    _ = [
                        event
                        async for event in agent_turn(
                            ProviderConfig("openai/test"),
                            ExecutionPolicy(),
                            workspace,
                            "hello",
                        )
                    ]
            records = workspace.read_history()
        self.assertEqual(records[0]["role"], "user")
        self.assertEqual(records[1]["role"], "assistant")
        self.assertEqual(records[1]["content"], "partial")
        self.assertEqual(records[2]["role"], "user")
        self.assertIn("error: ProviderError:", records[2]["content"])

    async def test_cancellation_persists_partial_output_and_user_message(self) -> None:
        delta_seen = asyncio.Event()

        async def cancellable_stream() -> object:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="partial", tool_calls=[]))]
            )
            await asyncio.Event().wait()

        async def consume(workspace: Workspace) -> None:
            async for event in agent_turn(
                ProviderConfig("openai/test"), ExecutionPolicy(), workspace, "hello"
            ):
                if isinstance(event, str):
                    delta_seen.set()

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with patch(
                "amnesia_agent_kernel.agent.acompletion",
                new=AsyncMock(return_value=cancellable_stream()),
            ):
                task = asyncio.create_task(consume(workspace))
                await asyncio.wait_for(delta_seen.wait(), timeout=1)
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            records = workspace.read_history()

        self.assertEqual(records[1]["role"], "assistant")
        self.assertEqual(records[1]["content"], "partial")
        self.assertEqual(records[2]["role"], "user")
        self.assertEqual(records[2]["content"], "user interrupted")

    async def test_falsey_history_input_is_rejected_without_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            workspace.update_history([{"role": "user", "content": "keep"}])
            with self.assertRaises(WorkspaceError):
                workspace.update_history(None)  # type: ignore[arg-type]
            self.assertEqual(workspace.read_history()[0]["content"], "keep")

    async def test_kind_history_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with self.assertRaises(WorkspaceError):
                workspace.update_history(
                    [{"kind": "turn_error", "message": "nope"}]  # type: ignore[list-item]
                )


if __name__ == "__main__":
    unittest.main()
