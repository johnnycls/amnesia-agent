import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from amnesia_agent_kernel.agent import agent_turn
from amnesia_agent_kernel.errors import ConfigError, ProviderError
from amnesia_agent_kernel.events import AssistantMessage, Delta, ToolResult
from amnesia_agent_kernel.provider import _request_kwargs
from amnesia_agent_kernel.streaming import _assistant_message
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
            1: {"id": "c2", "function": {"name": "bash", "arguments": "{}"}},
            0: {"id": "c1", "function": {"name": "bash", "arguments": '{"command":"ls"}'}},
        }
        message = _assistant_message(["Hel", "lo"], calls)
        self.assertEqual(message["content"], "Hello")
        self.assertEqual([call["id"] for call in message["tool_calls"]], ["c1", "c2"])

    def test_omits_tool_calls_key_when_absent(self) -> None:
        self.assertEqual(_assistant_message(["hi"], {}), {"role": "assistant", "content": "hi"})

    def test_rejects_tool_call_without_id(self) -> None:
        with self.assertRaises(ProviderError):
            _assistant_message([], {0: {"id": "", "function": {"name": "bash", "arguments": "{}"}}})


class AgentTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_yields_events_and_stops_on_plain_reply(self) -> None:
        calls: list[dict[str, Any]] = []
        responses: list[Any] = [
            stream(
                chunk(
                    tool_calls=[
                        call_delta(0, call_id="c1", name="bash", arguments='{"command":"ls"}')
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
                    async for event in agent_turn(
                        make_config(), ExecutionPolicy(), workspace, "hi"
                    )
                ]
            history_files = sorted(Path(directory, "history").glob("*.jsonl"))
            self.assertEqual(len(history_files), 1)
            history_roles = [
                json.loads(line)["role"]
                for line in history_files[0].read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            [type(event) for event in events],
            [AssistantMessage, ToolResult, Delta, Delta, AssistantMessage],
        )
        self.assertEqual(events[0].message["tool_calls"][0]["id"], "c1")
        self.assertEqual(events[1].message, tool_message)
        self.assertEqual(events[4].message["content"], "all done")
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
        self.assertIsInstance(events[-1], AssistantMessage)
        self.assertEqual(events[-1].message["content"], '{"answer":"ok"}')

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
        kwargs = _request_kwargs(config, messages=[], tools=[], response_format=response_format)
        self.assertEqual(kwargs["model"], "openai/test")
        self.assertEqual(kwargs["api_key"], "key")
        self.assertEqual(kwargs["api_base"], "https://example.com")
        self.assertEqual(kwargs["temperature"], 0.5)
        self.assertEqual(kwargs["response_format"], response_format)


if __name__ == "__main__":
    unittest.main()
