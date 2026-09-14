import asyncio
import json
import tempfile
import unittest
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from amnesia_agent_local_server.app import create_app
from amnesia_agent_local_server.config import ConfigStore
from amnesia_agent_local_server.session import SessionManager, TurnBusyError
from amnesia_agent_local_server.sse import event_envelope


class FakeSession:
    def __init__(self, provider: object, policy: object) -> None:
        self.provider = provider
        self.policy = policy

    async def turn(self, text: str, response_format: object = None):
        yield '{"answer":"'
        yield {
            "role": "assistant",
            "content": json.dumps({"answer": f"Echo: {text}", "choices": ["Again"]}),
        }

    def read_system_prompt(self) -> str:
        return "system"

    def update_system_prompt(self, content: str) -> None:
        pass

    def read_memory(self) -> str:
        return "memory"

    def update_memory(self, content: str) -> None:
        pass

    def list_history(self) -> list[str]:
        return []

    def read_history(self, date: str | None = None) -> list[dict[str, object]]:
        return []

    def update_history(self, messages: object, date: str | None = None) -> None:
        pass

    def reset_history(self) -> None:
        pass


class ClosingFakeSession(FakeSession):
    def __init__(self, provider: object, policy: object) -> None:
        super().__init__(provider, policy)
        self.closed = False

    async def turn(self, text: str, response_format: object = None):
        try:
            yield "partial"
            await asyncio.sleep(60)
            yield "unreachable"
        finally:
            self.closed = True


def _write_config(store: ConfigStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        '{"model":"openai/test","api_key":"test-key"}',
        encoding="utf-8",
    )


class SseTests(unittest.TestCase):
    def test_event_envelope_parses_structured_answer(self) -> None:
        payload = event_envelope(
            {"role": "assistant", "content": '{"answer":"Choose", "choices":["A", "B"]}'}
        )
        self.assertEqual(payload["type"], "assistant")
        self.assertEqual(payload["data"]["answer"], "Choose")
        self.assertEqual(payload["data"]["choices"], ["A", "B"])
        self.assertTrue(payload["data"]["structured"])

    def test_event_envelope_falls_back_to_plain_text(self) -> None:
        payload = event_envelope({"role": "assistant", "content": "plain text"})
        self.assertFalse(payload["data"]["structured"])
        self.assertEqual(payload["data"]["choices"], [])

    def test_event_envelope_maps_delta_and_tool_messages(self) -> None:
        self.assertEqual(
            event_envelope("chunk"),
            {"type": "delta", "data": {"text": "chunk"}},
        )
        tool_call = event_envelope(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            }
        )
        self.assertEqual(tool_call["type"], "tool_call")
        tool_result = event_envelope({"role": "tool", "content": "ok", "tool_call_id": "1"})
        self.assertEqual(tool_result, {"type": "tool_result", "data": {"content": "ok"}})

    def test_event_envelope_rejects_unknown_events(self) -> None:
        with self.assertRaises(ValueError):
            event_envelope({"role": "user", "content": "nope"})
        with self.assertRaises(ValueError):
            event_envelope(123)  # type: ignore[arg-type]

    def test_event_envelope_rejects_malformed_content(self) -> None:
        with self.assertRaises(ValueError):
            event_envelope({"role": "assistant", "content": {"nested": True}})
        with self.assertRaises(ValueError):
            event_envelope({"role": "assistant", "content": "", "tool_calls": "bad"})
        with self.assertRaises(ValueError):
            event_envelope({"role": "tool", "content": None})


class SessionTests(unittest.TestCase):
    def test_stream_turn_emits_done_and_releases_slot(self) -> None:
        async def run() -> list[dict[str, object]]:
            with tempfile.TemporaryDirectory() as directory:
                store = ConfigStore(directory)
                _write_config(store)
                manager = SessionManager(store)
                with patch("amnesia_agent_local_server.session.KernelSession", FakeSession):
                    events_agen = manager.start_turn("hello")
                    async with aclosing(events_agen):
                        events = [event async for event in events_agen]
                self.assertFalse(manager.active_turn)
                return events

        events = asyncio.run(run())
        self.assertEqual(events[0]["type"], "delta")
        self.assertEqual(events[1]["type"], "assistant")
        self.assertEqual(events[-1]["type"], "done")

    def test_cancel_active_turn_acloses_and_releases_busy(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = ConfigStore(directory)
                _write_config(store)
                manager = SessionManager(store)
                with patch(
                    "amnesia_agent_local_server.session.KernelSession", ClosingFakeSession
                ):
                    events_agen = manager.start_turn("hello")
                    assert isinstance(manager.get_session(), ClosingFakeSession)
                    session = manager.get_session()

                    async def consume() -> None:
                        async with aclosing(events_agen):
                            async for _event in events_agen:
                                await manager.cancel_active_turn()
                                break

                    await consume()
                    self.assertFalse(manager.active_turn)
                    self.assertTrue(session.closed)

        asyncio.run(run())

    def test_active_turn_blocks_config_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            _write_config(store)
            manager = SessionManager(store)
            manager._active = True
            with self.assertRaises(TurnBusyError):
                manager.update_config({"model": "openai/new"})
            with self.assertRaises(TurnBusyError):
                manager.setup_or_repair_workspace()
            with self.assertRaises(TurnBusyError):
                manager.create_or_reset_workspace()

    def test_turn_busy_returns_http_409(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            _write_config(store)
            client = TestClient(create_app(store), raise_server_exceptions=False)
            client.app.state.session._active = True
            response = client.put("/v1/config", json={"model": "openai/other"})
            self.assertEqual(response.status_code, 409)
            self.assertIn("detail", response.json())

    def test_health_and_shutdown_honesty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            app = create_app(store, instance_id="abc")
            client = TestClient(app)
            health = client.get("/v1/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(
                health.json(),
                {
                    "status": "ok",
                    "active_turn": False,
                    "api_version": "v1",
                    "instance_id": "abc",
                },
            )
            missing = client.post("/v1/shutdown")
            self.assertEqual(missing.status_code, 503)
            self.assertIn("detail", missing.json())

            app.state.uvicorn_server = SimpleNamespace(should_exit=False)
            shutdown = client.post("/v1/shutdown")
            self.assertEqual(shutdown.status_code, 200)
            self.assertEqual(shutdown.json(), {"shutting_down": True})
            self.assertTrue(app.state.uvicorn_server.should_exit)


if __name__ == "__main__":
    unittest.main()
