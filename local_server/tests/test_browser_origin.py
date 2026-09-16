import unittest

from fastapi.testclient import TestClient

from amnesia_agent_local_server.app import create_app
from amnesia_agent_local_server.browser_origin import is_allowed_browser_origin


class BrowserOriginPolicyTests(unittest.TestCase):
    def test_missing_origin_is_allowed_for_non_browser_clients(self) -> None:
        self.assertTrue(is_allowed_browser_origin(None))

    def test_loopback_http_origins_are_allowed(self) -> None:
        for origin in (
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.2:8080",
            "http://[::1]:9000",
        ):
            with self.subTest(origin=origin):
                self.assertTrue(is_allowed_browser_origin(origin))

    def test_non_loopback_and_null_origins_are_rejected(self) -> None:
        for origin in (
            "null",
            "file://",
            "https://localhost:3000",
            "http://example.com",
            "http://localhost.evil.example",
            "http://127.999.0.1:3000",
            "http://localhost/path",
        ):
            with self.subTest(origin=origin):
                self.assertFalse(is_allowed_browser_origin(origin))

    def test_allowed_origin_gets_cors_response_header(self) -> None:
        client = TestClient(create_app())
        response = client.get(
            "/v1/health",
            headers={"Origin": "http://localhost:5173"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_disallowed_origin_is_rejected_before_endpoint(self) -> None:
        client = TestClient(create_app())
        response = client.get(
            "/v1/health",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Browser origin is not allowed."})

    def test_null_origin_is_rejected(self) -> None:
        client = TestClient(create_app())
        response = client.get("/v1/health", headers={"Origin": "null"})
        self.assertEqual(response.status_code, 403)

    def test_disallowed_origin_cannot_submit_state_change(self) -> None:
        client = TestClient(create_app())
        response = client.put(
            "/v1/config",
            headers={"Origin": "https://evil.example"},
            json={"model": "openai/test"},
        )
        self.assertEqual(response.status_code, 403)

    def test_originless_state_change_requires_local_marker(self) -> None:
        client = TestClient(create_app())
        response = client.post("/v1/shutdown")
        self.assertEqual(response.status_code, 403)

    def test_local_marker_allows_originless_state_change(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/v1/shutdown",
            headers={"X-Amnesia-Client": "local"},
        )
        self.assertEqual(response.status_code, 503)

    def test_allowed_preflight_is_supported(self) -> None:
        client = TestClient(create_app())
        response = client.options(
            "/v1/config",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:3000",
        )

    def test_disallowed_preflight_is_rejected(self) -> None:
        client = TestClient(create_app())
        response = client.options(
            "/v1/config",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "PUT",
            },
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
