import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from amnesia_agent_kernel import ConfigError
from fastapi.testclient import TestClient

from amnesia_agent_local_server.app import create_app
from amnesia_agent_local_server.config import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_MAX_COMMAND_OUTPUT_BYTES,
    DEFAULT_MAX_CONTEXT_MESSAGE_CHARS,
    DEFAULT_MODEL,
    REDACTED_SENTINEL,
    ConfigStore,
    default_config_dict,
    public_config,
    redact_provider_params,
    reject_provider_params_secrets,
    resolve_request_workspace_path,
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
            self.assertEqual(values["max_context_message_chars"], DEFAULT_MAX_CONTEXT_MESSAGE_CHARS)
            self.assertNotIn("workspace_path", values)
            values.update({"model": "openai/test", "api_key": "secret"})
            store.path.write_text(json.dumps(values), encoding="utf-8")

            loaded = store.load()
            self.assertEqual(loaded.provider.api_key, "secret")
            public = public_config(loaded)
            self.assertTrue(public["api_key_set"])
            self.assertIsNone(public["api_key"])
            self.assertNotIn("workspace_path", public)

    def test_default_config_dict_matches_constants(self) -> None:
        defaults = default_config_dict()
        self.assertEqual(defaults["model"], DEFAULT_MODEL)
        self.assertEqual(defaults["command_timeout_seconds"], DEFAULT_COMMAND_TIMEOUT_SECONDS)
        self.assertNotIn("workspace_path", defaults)
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
            body = response.json()
            self.assertEqual(body["model"], "")
            self.assertNotIn("workspace_path", body)

    def test_reset_rewrites_constants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.setup()
            store.path.write_text(
                json.dumps(
                    {
                        "model": "openai/custom",
                        "api_key": "secret",
                    }
                ),
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
            reloaded = store.load()
            self.assertEqual(reloaded.provider.provider_params["temperature"], 0.2)

    def test_http_corrupt_config_returns_400(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text("{bad", encoding="utf-8")
            client = TestClient(create_app(store), raise_server_exceptions=False)
            response = client.get("/v1/config")
            self.assertEqual(response.status_code, 400)
            self.assertIn("detail", response.json())

    def test_legacy_workspace_path_in_config_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps({"model": "", "workspace_path": "/tmp/ws"}),
                encoding="utf-8",
            )
            with self.assertRaises(Exception) as ctx:
                store.load()
            self.assertIn("workspace_path", str(ctx.exception))

    def test_resolve_request_workspace_path(self) -> None:
        self.assertIsNone(resolve_request_workspace_path(None))
        self.assertIsNone(resolve_request_workspace_path(""))
        self.assertEqual(resolve_request_workspace_path("/tmp/custom"), "/tmp/custom")


class ProviderParamsRedactTests(unittest.TestCase):
    def test_redact_provider_params_masks_credentials(self) -> None:
        raw = {
            "temperature": 0.2,
            "api_key": "sk-secret",
            "api_base": "https://evil.example/v1",
            "extra_headers": {"Authorization": "Bearer x", "X-Custom": "y"},
            "nested": {"token": "t", "ok": 1},
        }
        redacted = redact_provider_params(raw)
        self.assertEqual(redacted["temperature"], 0.2)
        self.assertEqual(redacted["api_key"], REDACTED_SENTINEL)
        self.assertEqual(redacted["api_base"], REDACTED_SENTINEL)
        self.assertEqual(redacted["extra_headers"]["Authorization"], REDACTED_SENTINEL)
        self.assertEqual(redacted["extra_headers"]["X-Custom"], REDACTED_SENTINEL)
        self.assertEqual(redacted["nested"]["token"], REDACTED_SENTINEL)
        self.assertEqual(redacted["nested"]["ok"], 1)
        # Original unchanged.
        self.assertEqual(raw["api_key"], "sk-secret")

    def test_reject_provider_params_secrets_fails_loud(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            reject_provider_params_secrets(
                {
                    "api_key": "sk-...",
                    "extra_headers": {"Authorization": "Bearer x"},
                }
            )
        message = str(ctx.exception)
        self.assertIn("api_key", message)
        self.assertIn("extra_headers.Authorization", message)

    def test_reject_allows_safe_params(self) -> None:
        reject_provider_params_secrets({"temperature": 0.1, "max_tokens": 16})

    def test_public_config_redacts_provider_params(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps(
                    {
                        "model": "openai/test",
                        "api_key": "top-secret",
                        "provider_params": {
                            "temperature": 0.5,
                            "api_key": "sk-nested",
                            "extra_headers": {"Authorization": "Bearer x"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            public = public_config(store.load())
            self.assertIsNone(public["api_key"])
            self.assertTrue(public["api_key_set"])
            self.assertEqual(public["provider_params"]["temperature"], 0.5)
            self.assertEqual(public["provider_params"]["api_key"], REDACTED_SENTINEL)
            self.assertEqual(
                public["provider_params"]["extra_headers"]["Authorization"],
                REDACTED_SENTINEL,
            )

    def test_http_put_rejects_credential_provider_params(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            client = TestClient(create_app(store), raise_server_exceptions=False)
            response = client.put(
                "/v1/config",
                json={
                    "model": "openai/test",
                    "provider_params": {
                        "api_key": "sk-...",
                        "extra_headers": {"Authorization": "Bearer x"},
                    },
                },
            )
            self.assertEqual(response.status_code, 400)
            detail = response.json()["detail"]
            self.assertIn("provider_params", detail)
            self.assertIn("api_key", detail)

    def test_http_put_safe_params_then_get_has_no_raw_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            # Seed secrets on disk (legacy / manual edit); public GET must redact.
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps(
                    {
                        "model": "openai/test",
                        "api_key": "top-secret",
                        "provider_params": {
                            "temperature": 0.3,
                            "api_key": "sk-nested",
                            "extra_headers": {"Authorization": "Bearer x"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(store))
            got = client.get("/v1/config")
            self.assertEqual(got.status_code, 200)
            body = got.json()
            dumped = json.dumps(body)
            self.assertNotIn("sk-nested", dumped)
            self.assertNotIn("Bearer x", dumped)
            self.assertNotIn("top-secret", dumped)
            self.assertEqual(body["provider_params"]["temperature"], 0.3)
            self.assertEqual(body["provider_params"]["api_key"], REDACTED_SENTINEL)

            ok = client.put(
                "/v1/config",
                json={"provider_params": {"temperature": 0.7}},
            )
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["provider_params"]["temperature"], 0.7)


class ApiKeyUpdateTests(unittest.TestCase):
    def test_blank_api_key_leaves_stored_key_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps({"model": "openai/test", "api_key": "secret-key"}),
                encoding="utf-8",
            )
            client = TestClient(create_app(store))
            response = client.put("/v1/config", json={"model": "openai/other", "api_key": ""})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["api_key_set"])
            loaded = store.load()
            self.assertEqual(loaded.provider.model, "openai/other")
            self.assertEqual(loaded.provider.api_key, "secret-key")

    def test_api_key_clear_removes_stored_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps({"model": "openai/test", "api_key": "secret-key"}),
                encoding="utf-8",
            )
            client = TestClient(create_app(store))
            response = client.put("/v1/config", json={"api_key_clear": True})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertFalse(body["api_key_set"])
            self.assertIsNone(body["api_key"])
            loaded = store.load()
            self.assertIsNone(loaded.provider.api_key)

    def test_api_key_clear_with_new_key_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps({"model": "openai/test", "api_key": "secret-key"}),
                encoding="utf-8",
            )
            client = TestClient(create_app(store), raise_server_exceptions=False)
            response = client.put(
                "/v1/config",
                json={"api_key_clear": True, "api_key": "new-secret"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("api_key_clear", response.json()["detail"])

    @unittest.skipIf(
        os.name == "nt",
        "NTFS ignores POSIX 0o600; st_mode & 0o777 stays 0o666 on Windows",
    )
    def test_atomic_write_sets_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.write_defaults()
            mode = store.path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


class WorkspaceApiTests(unittest.TestCase):
    def test_workspace_lifecycle_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            client = TestClient(create_app(store))
            with patch(
                "amnesia_agent_local_server.session.KernelSession.check_workspace",
                return_value=False,
            ) as check:
                response = client.get("/v1/workspace/check")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": False})
            check.assert_called_once_with(None)

            with patch(
                "amnesia_agent_local_server.session.KernelSession.setup_or_repair_workspace"
            ) as setup:
                response = client.post("/v1/workspace/setup-or-repair")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            setup.assert_called_once_with(None)

            with patch(
                "amnesia_agent_local_server.session.KernelSession.create_workspace"
            ) as create:
                response = client.post("/v1/workspace/create")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            create.assert_called_once_with(None)

            with patch(
                "amnesia_agent_local_server.session.KernelSession.create_or_reset_workspace"
            ) as reset:
                response = client.post("/v1/workspace/create-or-reset")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            reset.assert_called_once_with(None)

            gone = client.post("/v1/workspace/system-prompt/reset")
            self.assertEqual(gone.status_code, 404)
            gone = client.post("/v1/workspace/memory/reset")
            self.assertEqual(gone.status_code, 404)

    def test_workspace_lifecycle_uses_request_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            custom = str(Path(directory) / "custom-ws")
            client = TestClient(create_app(store))

            with patch(
                "amnesia_agent_local_server.session.KernelSession.check_workspace",
                return_value=True,
            ) as check:
                response = client.get("/v1/workspace/check", params={"workspace_path": custom})
            self.assertEqual(response.status_code, 200)
            check.assert_called_once_with(custom)

            with patch(
                "amnesia_agent_local_server.session.KernelSession.setup_or_repair_workspace"
            ) as setup:
                client.post(
                    "/v1/workspace/setup-or-repair",
                    json={"workspace_path": custom},
                )
            setup.assert_called_once_with(custom)

            with patch(
                "amnesia_agent_local_server.session.KernelSession.create_workspace"
            ) as create:
                client.post(
                    "/v1/workspace/create",
                    json={"workspace_path": custom},
                )
            create.assert_called_once_with(custom)

            with patch(
                "amnesia_agent_local_server.session.KernelSession.create_or_reset_workspace"
            ) as reset:
                client.post(
                    "/v1/workspace/create-or-reset",
                    json={"workspace_path": custom},
                )
            reset.assert_called_once_with(custom)

    def test_create_workspace_nonempty_returns_400(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            ws = Path(directory) / "occupied"
            ws.mkdir()
            (ws / "notes.txt").write_text("stay", encoding="utf-8")
            client = TestClient(create_app(store))
            response = client.post(
                "/v1/workspace/create",
                json={"workspace_path": str(ws)},
            )
            self.assertEqual(response.status_code, 400)
            detail = response.json().get("detail", "")
            self.assertIn("not empty", detail.lower())
            self.assertEqual((ws / "notes.txt").read_text(encoding="utf-8"), "stay")

    def test_workspace_get_empty_query_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            client = TestClient(create_app(store))
            with patch(
                "amnesia_agent_local_server.session.KernelSession.check_workspace",
                return_value=True,
            ) as check:
                response = client.get("/v1/workspace/check", params={"workspace_path": ""})
            self.assertEqual(response.status_code, 200)
            check.assert_called_once_with(None)

    def test_update_history_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                '{"model":"openai/test","api_key":"test-key"}',
                encoding="utf-8",
            )
            client = TestClient(create_app(store))
            custom = str(Path(directory) / "ws")

            class FakeSession:
                def __init__(
                    self,
                    provider: object,
                    policy: object,
                    workspace_root: object = None,
                ) -> None:
                    self.provider = provider
                    self.policy = policy
                    self.workspace_root = workspace_root
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

            with patch("amnesia_agent_local_server.session.KernelSession", FakeSession):
                response = client.put(
                    "/v1/workspace/history",
                    json={
                        "messages": [{"role": "user", "content": "hi"}],
                        "date": "2026-09-14",
                        "workspace_path": custom,
                    },
                )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["date"], "2026-09-14")
            self.assertEqual(body["messages"][0]["content"], "hi")

            created: list[FakeSession] = []

            class TrackingSession(FakeSession):
                def __init__(self, *args: object, **kwargs: object) -> None:
                    super().__init__(*args, **kwargs)
                    created.append(self)

            with patch("amnesia_agent_local_server.session.KernelSession", TrackingSession):
                client.put(
                    "/v1/workspace/history",
                    json={
                        "messages": [{"role": "user", "content": "hi"}],
                        "workspace_path": custom,
                    },
                )
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].workspace_root, custom)

    def test_content_put_passes_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                '{"model":"openai/test","api_key":"test-key"}',
                encoding="utf-8",
            )
            client = TestClient(create_app(store))
            custom = str(Path(directory) / "ws")
            created: list[object] = []

            class FakeSession:
                def __init__(
                    self,
                    provider: object,
                    policy: object,
                    workspace_root: object = None,
                ) -> None:
                    self.workspace_root = workspace_root
                    created.append(self)

                def update_system_prompt(self, content: str) -> None:
                    self.content = content

                def update_memory(self, content: str) -> None:
                    self.content = content

            with patch("amnesia_agent_local_server.session.KernelSession", FakeSession):
                prompt = client.put(
                    "/v1/workspace/system-prompt",
                    json={"content": "sys", "workspace_path": custom},
                )
                memory = client.put(
                    "/v1/workspace/memory",
                    json={"content": "mem", "workspace_path": custom},
                )
            self.assertEqual(prompt.status_code, 200)
            self.assertEqual(memory.status_code, 200)
            self.assertEqual(len(created), 2)
            self.assertEqual(created[0].workspace_root, custom)  # type: ignore[attr-defined]
            self.assertEqual(created[1].workspace_root, custom)  # type: ignore[attr-defined]

    def test_invalid_workspace_path_returns_400(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            # A path that exists as a file is invalid for create/reset.
            bad = Path(directory) / "not-a-dir"
            bad.write_text("x", encoding="utf-8")
            client = TestClient(create_app(store), raise_server_exceptions=False)
            response = client.post(
                "/v1/workspace/create-or-reset",
                json={"workspace_path": str(bad)},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("detail", response.json())


if __name__ == "__main__":
    unittest.main()
