"""Tests for the Flask ``require_auth`` before-request hook.

Validates that:
- Protected routes redirect to /login when the session cookie is missing.
- Public routes are accessible without authentication.
- Static and /api/ paths are exempt from the gate.
- Mock mode disables the gate entirely.
"""

import pytest


# Paths that should be gated
GATED_PATHS = [
    "/",
    "/account",
    "/mealbot",
    "/mealbot/individualized",
]

# Paths that should NOT be gated
EXEMPT_PATHS = [
    "/login",
    "/auth/callback",
    "/auth/complete-registration",
    "/auth/claim-account",
]


class TestAuthGateRedirect:
    """Without a session cookie, protected paths redirect to /login."""

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_redirect_to_login(self, unauthed_client, path):
        resp = unauthed_client.get(path)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestAuthGateExemptions:
    """Public paths, static files, and /api/ are never gated."""

    @pytest.mark.parametrize("path", EXEMPT_PATHS)
    def test_public_pages_no_redirect(self, unauthed_client, path):
        resp = unauthed_client.get(path)
        assert resp.status_code == 200

    def test_static_exempt(self, unauthed_client):
        resp = unauthed_client.get("/static/css/main.css")
        assert resp.status_code == 200

    def test_api_proxy_exempt(self, unauthed_client, monkeypatch):
        """The /api/ prefix is exempt from the auth gate (proxied to backend)."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", False)
        resp = unauthed_client.get("/api/v2/health")
        # Returns 404 because proxy is disabled, but should NOT be a 302 redirect
        assert resp.status_code != 302


class TestAuthGateMockBypass:
    """In mock mode, the auth gate is completely bypassed."""

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_no_redirect_in_mock_mode(self, mock_client, path):
        resp = mock_client.get(path)
        assert resp.status_code == 200


class TestAuthGateWithCookie:
    """With a valid session cookie, protected routes are accessible."""

    @pytest.mark.parametrize("path", GATED_PATHS)
    def test_authenticated_access(self, authed_client, path):
        resp = authed_client.get(path)
        assert resp.status_code == 200


class TestAuthGateCookieNameMismatch:
    """A cookie with the wrong name does not satisfy the auth gate."""

    def test_wrong_cookie_name_triggers_redirect(self, app, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_MOCK", False)
        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "SESSION_COOKIE_NAME", "correct.session")
        c = app.test_client()
        c.set_cookie("wrong.session", "some-value", domain="localhost")
        resp = c.get("/account")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
