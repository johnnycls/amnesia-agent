"""Remote pairing and bearer authentication tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amnesia_agent_server.app import create_app
from amnesia_agent_server.config import ConfigStore
from tests.client import LocalTestClient as TestClient


class PairingTests(unittest.TestCase):
    def test_one_time_pairing_issues_token_and_authenticates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory))
            app = create_app(
                store,
                remote=True,
                public_url="https://agent.example.com",
            )
            with TestClient(app) as client:
                payload = app.state.pairing_manager.current_payload()
                response = client.post(
                    "/v1/pair",
                    json={"code": payload.code, "device_name": "phone"},
                )
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["server_url"], "https://agent.example.com")
                token = result["device_token"]
                self.assertTrue(token)

                health = client.get(
                    "/v1/health",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(health.status_code, 200)

                replay = client.post(
                    "/v1/pair",
                    json={"code": payload.code, "device_name": "again"},
                )
                self.assertEqual(replay.status_code, 400)

    def test_remote_routes_reject_missing_or_invalid_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                ConfigStore(Path(directory)),
                remote=True,
                public_url="https://agent.example.com",
            )
            with TestClient(app) as client:
                self.assertEqual(client.get("/v1/health").status_code, 401)
                self.assertEqual(
                    client.get(
                        "/v1/health",
                        headers={"Authorization": "Bearer invalid"},
                    ).status_code,
                    401,
                )

    def test_remote_workspace_is_confined_to_default_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            app = create_app(
                ConfigStore(Path(directory) / "config"),
                remote=True,
                public_url="https://agent.example.com",
                workspace_root=str(root),
            )
            with TestClient(app) as client:
                payload = app.state.pairing_manager.current_payload()
                token = client.post(
                    "/v1/pair", json={"code": payload.code}
                ).json()["device_token"]
                response = client.get(
                    "/v1/workspace/check",
                    params={"workspace_path": str(Path(directory) / "outside")},
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 400)

    def test_remote_shutdown_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                ConfigStore(Path(directory)),
                remote=True,
                public_url="https://agent.example.com",
            )
            with TestClient(app) as client:
                payload = app.state.pairing_manager.current_payload()
                token = client.post(
                    "/v1/pair", json={"code": payload.code}
                ).json()["device_token"]
                response = client.post(
                    "/v1/shutdown",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
