import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from amnesia_agent_local_server.app import create_app
from amnesia_agent_local_server.config import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_MAX_COMMAND_OUTPUT_BYTES,
    DEFAULT_MAX_CONTEXT_MESSAGE_CHARS,
    DEFAULT_MODEL,
    ConfigStore,
    default_config_dict,
    public_config,
)


class ConfigStoreTests(unittest.TestCase):
    def test_store_seeds_from_constants_and_masks_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.setup()
            values = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(values["model"], DEFAULT_MODEL)
            self.assertEqual(values["command_timeout_seconds"], DEFAULT_COMMAND_TIMEOUT_SECONDS)
            self.assertEqual(values["max_command_output_bytes"], DEFAULT_MAX_COMMAND_OUTPUT_BYTES)
            self.assertEqual(
                values["max_context_message_chars"], DEFAULT_MAX_CONTEXT_MESSAGE_CHARS
            )
            values.update({"model": "openai/test", "api_key": "secret"})
            store.path.write_text(json.dumps(values), encoding="utf-8")

            loaded = store.load()
            self.assertEqual(loaded.provider.api_key, "secret")
            public = public_config(loaded)
            self.assertTrue(public["api_key_set"])
            self.assertIsNone(public["api_key"])

    def test_default_config_dict_matches_constants(self) -> None:
        defaults = default_config_dict()
        self.assertEqual(defaults["model"], DEFAULT_MODEL)
        self.assertEqual(defaults["command_timeout_seconds"], DEFAULT_COMMAND_TIMEOUT_SECONDS)
        defaults["model"] = "mutated"
        self.assertEqual(default_config_dict()["model"], DEFAULT_MODEL)

    def test_corrupt_config_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(Exception) as ctx:
                store.load()
            self.assertIn("Malformed JSON", str(ctx.exception))

    def test_blank_default_config_is_available_to_settings_ui(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            client = TestClient(create_app(store))
            response = client.get("/v1/config")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["model"], "")

    def test_reset_rewrites_constants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.setup()
            store.path.write_text(
                json.dumps({"model": "openai/custom", "api_key": "secret"}),
                encoding="utf-8",
            )
            reset = store.reset()
            self.assertEqual(reset.provider.model, DEFAULT_MODEL)
            on_disk = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, default_config_dict())

    def test_save_is_readable_and_preserves_provider_params(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps(
                    {
                        "model": "openai/test",
                        "api_key": "secret",
                        "provider_params": {"temperature": 0.2},
                    }
                ),
                encoding="utf-8",
            )
            loaded = store.load()
            store.save(loaded)
            self.assertEqual(store.load().provider.provider_params["temperature"], 0.2)

    def test_http_corrupt_config_returns_400(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text("{bad", encoding="utf-8")
            client = TestClient(create_app(store), raise_server_exceptions=False)
            response = client.get("/v1/config")
            self.assertEqual(response.status_code, 400)
            self.assertIn("detail", response.json())


class WorkspaceApiTests(unittest.TestCase):
    def test_workspace_lifecycle_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            client = TestClient(create_app(store))
            with patch(
                "amnesia_agent_local_server.session.KernelSession.check_workspace",
                return_value=False,
            ):
                response = client.get("/v1/workspace/check")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": False})

            with patch(
                "amnesia_agent_local_server.session.KernelSession.setup_or_repair_workspace"
            ) as setup:
                response = client.post("/v1/workspace/setup-or-repair")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            setup.assert_called_once_with()

            with patch(
                "amnesia_agent_local_server.session.KernelSession.create_or_reset_workspace"
            ) as reset:
                response = client.post("/v1/workspace/create-or-reset")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            reset.assert_called_once_with()

            gone = client.post("/v1/workspace/system-prompt/reset")
            self.assertEqual(gone.status_code, 404)
            gone = client.post("/v1/workspace/memory/reset")
            self.assertEqual(gone.status_code, 404)

    def test_update_history_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                '{"model":"openai/test","api_key":"test-key"}',
                encoding="utf-8",
            )
            client = TestClient(create_app(store))

            class FakeSession:
                def __init__(self, provider: object, policy: object) -> None:
                    self.provider = provider
                    self.policy = policy
                    self.updated: list[object] = []

                def update_history(self, messages: object, date: str | None = None) -> None:
                    self.updated.append((messages, date))

                def list_history(self) -> list[str]:
                    return []

                def read_history(self, date: str | None = None) -> list[object]:
                    return []

                def read_system_prompt(self) -> str:
                    return ""

                def read_memory(self) -> str:
                    return ""

            with patch(
                "amnesia_agent_local_server.session.KernelSession", FakeSession
            ):
                response = client.put(
                    "/v1/workspace/history",
                    json={
                        "messages": [{"role": "user", "content": "hi"}],
                        "date": "2026-09-14",
                    },
                )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["date"], "2026-09-14")
            self.assertEqual(body["messages"][0]["content"], "hi")


if __name__ == "__main__":
    unittest.main()
