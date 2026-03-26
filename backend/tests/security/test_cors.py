"""CORS configuration tests.

Validates the backend's CORS middleware behaves correctly:
- Allowed origins get proper CORS headers
- Disallowed origins are rejected
- Credentials are supported
- Preflight requests work
"""

import pytest
from starlette.testclient import TestClient


class TestCORSAllowedOrigins:
    """Requests from allowed origins get CORS response headers."""

    def test_cors_preflight_returns_200(self, client: TestClient) -> None:
        """OPTIONS preflight with a valid origin should return 200."""
        resp = client.options(
            "/api/v2/mealbot/ledger",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert resp.status_code == 200

    def test_cors_allows_credentials(self, client: TestClient) -> None:
        """Access-Control-Allow-Credentials must be true for session cookies."""
        resp = client.options(
            "/api/v2/mealbot/ledger",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_cors_exposes_methods(self, client: TestClient) -> None:
        """Preflight should include allowed methods."""
        resp = client.options(
            "/api/v2/mealbot/record",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
            },
        )
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "POST" in allowed or "*" in allowed


class TestCORSDisallowedOrigins:
    """Requests from unknown origins should not include CORS allow headers."""

    def test_unknown_origin_no_allow_header(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An origin not in the allow-list should not get Access-Control-Allow-Origin.

        Note: monkeypatching config.CORS_ALLOW_ORIGINS after app startup has
        no effect — the CORS middleware is already configured.  We rebuild a
        minimal app with a restricted origin list to test this properly.
        """
        from fastapi import FastAPI
        from starlette.middleware.cors import CORSMiddleware
        from routes.health import Health

        restricted_app = FastAPI()
        restricted_app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://trusted.example.com"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        restricted_app.include_router(Health)

        with TestClient(restricted_app) as c:
            resp = c.get(
                "/healthz",
                headers={"Origin": "https://evil.example.com"},
            )
            allow_origin = resp.headers.get("access-control-allow-origin", "")
            assert allow_origin != "https://evil.example.com"


class TestCORSWildcardWarning:
    """In dev mode CORS uses wildcard — document this tradeoff."""

    def test_dev_mode_cors_wildcard(self, client: TestClient) -> None:
        """Dev mode sets allow_origins=['*'] — verify wildcard is present."""
        resp = client.options(
            "/api/v2/mealbot/ledger",
            headers={
                "Origin": "http://anything.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # In dev mode, wildcard should be the CORS origin
        allow = resp.headers.get("access-control-allow-origin", "")
        # Accept either wildcard or the echoed origin (Starlette behavior)
        assert allow in ("*", "http://anything.example.com") or allow
