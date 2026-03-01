"""Cache header tests for the backend API.

Validates that API responses have appropriate caching directives.
"""

import pytest
from starlette.testclient import TestClient


class TestAPICacheHeaders:
    """API responses should have appropriate cache directives."""

    def test_profile_no_cache(self, authenticated_client: TestClient) -> None:
        """User-specific data should not be cached by intermediaries."""
        resp = authenticated_client.get("/api/v2/account/profile")
        assert resp.status_code == 200
        cc = resp.headers.get("cache-control", "")
        # User data should not be publicly cached
        if cc:
            assert "public" not in cc.lower()

    def test_events_response_headers(self, authenticated_client: TestClient) -> None:
        """Event list should include standard response headers."""
        resp = authenticated_client.get("/api/v2/happyhour/events")
        assert resp.status_code == 200
        assert "content-type" in resp.headers


class TestSecurityHeaders:
    """Responses should include basic security headers."""

    def test_content_type_header_present(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/api/v2/account/profile")
        assert "content-type" in resp.headers
        assert "application/json" in resp.headers["content-type"]

    def test_no_server_version_leaked(self, client: TestClient) -> None:
        """The Server header should not leak internal version info."""
        resp = client.get("/api/v2/happyhour/events")
        server = resp.headers.get("server", "")
        # Should not contain software versions
        assert "Python" not in server
        assert "Starlette" not in server
