import asyncio
import json
import tempfile
import unittest
from contextlib import aclosing
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from amnesia_agent_kernel.agent import agent_turn
from amnesia_agent_kernel.errors import ConfigError, ProviderError
from amnesia_agent_kernel.provider import request_kwargs
from amnesia_agent_kernel.streaming import assistant_message
from amnesia_agent_kernel.types import ExecutionPolicy, ProviderConfig
from amnesia_agent_kernel.workspace import Workspace


def chunk(content: str | None = None, tool_calls: list[Any] | None = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def call_delta(
    index: int,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> Any:
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


async def stream(*chunks: Any) -> Any:
    for item in chunks:
        yield item


def make_config() -> ProviderConfig:
    return ProviderConfig(model="openai/test")


class AssistantMessageTests(unittest.TestCase):
    def test_assembles_content_and_ordered_tool_calls(self) -> None:
        calls = {
            1: {"id": "c2", "function": {"name": "shell", "arguments": "{}"}},
            0: {"id": "c1", "function": {"name": "shell", "arguments": '{"command":"ls"}'}},
        }
        message = assistant_message(["Hel", "lo"], calls)
        self.assertEqual(message["content"], "Hello")
        self.assertEqual([call["id"] for call in message["tool_calls"]], ["c1", "c2"])

    def test_omits_tool_calls_key_when_absent(self) -> None:
        self.assertEqual(assistant_message(["hi"], {}), {"role": "assistant", "content": "hi"})

    def test_rejects_tool_call_without_id(self) -> None:
        with self.assertRaises(ProviderError):
            assistant_message([], {0: {"id": "", "function": {"name": "shell", "arguments": "{}"}}})


class AgentTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_yields_events_and_stops_on_plain_reply(self) -> None:
        calls: list[dict[str, Any]] = []
        responses: list[Any] = [
            stream(
                chunk(
                    tool_calls=[
                        call_delta(0, call_id="c1", name="shell", arguments='{"command":"ls"}')
                    ]
                )
            ),
            stream(chunk(content="all "), chunk(content="done")),
        ]

        async def fake_completion(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return responses.pop(0)

        tool_message: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "out",
        }
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with (
                patch("amnesia_agent_kernel.agent.acompletion", new=fake_completion),
                patch(
                    "amnesia_agent_kernel.agent.execute_tool_calls",
                    new=AsyncMock(return_value=[tool_message]),
                ) as execute,
            ):
                events = [
                    event
                    async for event in agent_turn(make_config(), ExecutionPolicy(), workspace, "hi")
                ]
            history_files = sorted(Path(directory, "history").glob("*.jsonl"))
            self.assertEqual(len(history_files), 1)
            history_roles = [
                json.loads(line)["role"]
                for line in history_files[0].read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(events), 5)
        self.assertIsInstance(events[0], dict)
        self.assertEqual(events[0]["role"], "assistant")
        self.assertEqual(events[0]["tool_calls"][0]["id"], "c1")
        self.assertEqual(events[1], tool_message)
        self.assertEqual(events[1]["role"], "tool")
        self.assertEqual(events[2], "all ")
        self.assertEqual(events[3], "done")
        self.assertIsInstance(events[4], dict)
        self.assertEqual(events[4]["role"], "assistant")
        self.assertEqual(events[4]["content"], "all done")
        execute.assert_awaited_once()

        self.assertEqual(len(calls), 2)
        first_messages = calls[0]["messages"]
        self.assertEqual(first_messages[0], {"role": "user", "content": "hi"})
        second_messages = calls[1]["messages"]
        self.assertEqual(len(second_messages), 3)
        self.assertEqual(second_messages[2], tool_message)
        self.assertEqual(history_roles, ["user", "assistant", "tool", "assistant"])

    async def test_structured_response_format_is_forwarded_on_each_model_request(self) -> None:
        calls: list[dict[str, Any]] = []

        async def fake_completion(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return stream(chunk(content='{"answer":"ok"}'))

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
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with patch("amnesia_agent_kernel.agent.acompletion", new=fake_completion):
                events = [
                    event
                    async for event in agent_turn(
                        make_config(),
                        ExecutionPolicy(),
                        workspace,
                        "hi",
                        response_format,
                    )
                ]

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["response_format"], response_format)
        self.assertEqual(events[0], '{"answer":"ok"}')
        self.assertIsInstance(events[-1], dict)
        self.assertEqual(events[-1]["role"], "assistant")
        self.assertEqual(events[-1]["content"], '{"answer":"ok"}')

    async def test_structured_response_format_must_be_json_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with self.assertRaises(ConfigError):
                [
                    event
                    async for event in agent_turn(
                        make_config(),
                        ExecutionPolicy(),
                        workspace,
                        "hi",
                        {"type": object()},
                    )
                ]


    async def test_aclose_closes_provider_stream(self) -> None:
        class ClosingStream:
            def __init__(self, chunks: list[Any]) -> None:
                self._chunks = list(chunks)
                self.closed = False

            def __aiter__(self) -> "ClosingStream":
                return self

            async def __anext__(self) -> Any:
                if not self._chunks:
                    raise StopAsyncIteration
                item = self._chunks.pop(0)
                if item is None:
                    await asyncio.sleep(60)
                    raise StopAsyncIteration
                return item

            async def aclose(self) -> None:
                self.closed = True

        held: list[ClosingStream] = []

        async def fake_completion(**kwargs: Any) -> Any:
            stream_obj = ClosingStream([chunk(content="hi"), None])
            held.append(stream_obj)
            return stream_obj

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with patch("amnesia_agent_kernel.agent.acompletion", new=fake_completion):
                agen = agent_turn(make_config(), ExecutionPolicy(), workspace, "hi")
                async with aclosing(agen):
                    first = await agen.__anext__()
                    self.assertEqual(first, "hi")
                    await agen.aclose()
            self.assertEqual(len(held), 1)
            self.assertTrue(held[0].closed)
            history = workspace.read_history()
            self.assertTrue(
                any("user interrupted" in str(item.get("content", "")) for item in history)
            )


    async def test_cancel_during_pending_acompletion(self) -> None:
        started = asyncio.Event()

        async def hanging_completion(**kwargs: Any) -> Any:
            started.set()
            await asyncio.sleep(60)
            return stream(chunk(content="unreachable"))

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with patch("amnesia_agent_kernel.agent.acompletion", new=hanging_completion):

                async def consume() -> None:
                    agen = agent_turn(make_config(), ExecutionPolicy(), workspace, "hi")
                    async with aclosing(agen):
                        async for _event in agen:
                            pass

                task = asyncio.create_task(consume())
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            history = workspace.read_history()
            self.assertTrue(
                any("user interrupted" in str(item.get("content", "")) for item in history)
            )

    async def test_cancel_during_tool_execution_cancels_tools(self) -> None:
        tool_started = asyncio.Event()
        tool_cancelled = asyncio.Event()

        async def fake_completion(**kwargs: Any) -> Any:
            return stream(
                chunk(
                    tool_calls=[
                        call_delta(
                            0, call_id="c1", name="shell", arguments='{"command":"sleep 60"}'
                        )
                    ]
                )
            )

        async def hanging_tools(*args: Any, **kwargs: Any) -> Any:
            tool_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                tool_cancelled.set()
                raise
            return [{"role": "tool", "tool_call_id": "c1", "content": "unreachable"}]

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with (
                patch("amnesia_agent_kernel.agent.acompletion", new=fake_completion),
                patch("amnesia_agent_kernel.agent.execute_tool_calls", new=hanging_tools),
            ):

                async def consume() -> None:
                    agen = agent_turn(make_config(), ExecutionPolicy(), workspace, "hi")
                    async with aclosing(agen):
                        async for _event in agen:
                            pass

                task = asyncio.create_task(consume())
                await tool_started.wait()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(tool_cancelled.is_set())
            history = workspace.read_history()
            self.assertTrue(
                any("user interrupted" in str(item.get("content", "")) for item in history)
            )

    async def test_request_kwargs_give_config_priority_over_provider_params(self) -> None:
        config = ProviderConfig(
            model="openai/test",
            api_key="key",
            base_url="https://example.com",
            provider_params={
                "model": "sneaky",
                "response_format": "sneaky",
                "temperature": 0.5,
            },
        )
        response_format = {"type": "json_object"}
        kwargs = request_kwargs(config, messages=[], tools=[], response_format=response_format)
        self.assertEqual(kwargs["model"], "openai/test")
        self.assertEqual(kwargs["api_key"], "key")
        self.assertEqual(kwargs["api_base"], "https://example.com")
        self.assertEqual(kwargs["temperature"], 0.5)
        self.assertEqual(kwargs["response_format"], response_format)


if __name__ == "__main__":
    unittest.main()
