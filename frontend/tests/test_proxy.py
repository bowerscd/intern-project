"""Tests for the /api/* reverse proxy.

Uses ``responses`` to mock the backend HTTP calls so no real backend is needed.
"""

import pytest
import responses


class TestProxyEnabled:
    """When USE_PROXY=True, /api/* requests are forwarded to BACKEND_URL."""

    @responses.activate
    def test_get_proxied(self, app, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            responses.GET,
            "http://mock-backend:8000/api/v2/account/profile",
            json={"id": 1, "username": "alice"},
            status=200,
        )

        c = app.test_client()
        resp = c.get("/api/v2/account/profile")
        assert resp.status_code == 200
        assert resp.get_json()["username"] == "alice"

    @responses.activate
    def test_post_proxied_with_body(self, app, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            responses.POST,
            "http://mock-backend:8000/api/v2/mealbot/record",
            json={"status": "ok"},
            status=201,
        )

        c = app.test_client()
        resp = c.post(
            "/api/v2/mealbot/record",
            json={"payer": "alice", "recipient": "bob", "credits": 1},
        )
        assert resp.status_code == 201

    @responses.activate
    def test_query_string_forwarded(self, app, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            responses.GET,
            "http://mock-backend:8000/api/v2/mealbot/ledger?limit=5",
            json=[],
            status=200,
        )

        c = app.test_client()
        resp = c.get("/api/v2/mealbot/ledger?limit=5")
        assert resp.status_code == 200

    @responses.activate
    def test_cookies_forwarded(self, app, monkeypatch):
        """Session cookies are relayed to the backend."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        def request_callback(request):
            # Verify cookie was forwarded
            assert "localhost.session" in (request.headers.get("Cookie", "") or "")
            return (200, {}, '{"ok": true}')

        responses.add_callback(
            responses.GET,
            "http://mock-backend:8000/api/v2/account/profile",
            callback=request_callback,
            content_type="application/json",
        )

        c = app.test_client()
        c.set_cookie("localhost.session", "signed-value", domain="localhost")
        resp = c.get("/api/v2/account/profile")
        assert resp.status_code == 200

    @responses.activate
    def test_set_cookie_relayed_to_browser(self, app, monkeypatch):
        """Set-Cookie headers from the backend are passed through to the browser."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            responses.GET,
            "http://mock-backend:8000/api/v2/auth/callback/test",
            status=302,
            headers={
                "Location": "/account",
                "Set-Cookie": "localhost.session=abc123; Path=/; HttpOnly",
            },
        )

        c = app.test_client()
        resp = c.get("/api/v2/auth/callback/test?code=xyz&state=s")
        assert resp.status_code == 302
        # The Set-Cookie header should be relayed
        set_cookie = resp.headers.get("Set-Cookie", "")
        assert "localhost.session" in set_cookie

    @responses.activate
    def test_forwarded_headers_added(self, app, monkeypatch):
        """X-Forwarded-For and X-Forwarded-Host are added to proxied requests."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        def request_callback(request):
            assert "X-Forwarded-For" in request.headers
            assert "X-Forwarded-Host" in request.headers
            return (200, {}, '{"ok": true}')

        responses.add_callback(
            responses.GET,
            "http://mock-backend:8000/api/v2/health",
            callback=request_callback,
            content_type="application/json",
        )

        c = app.test_client()
        resp = c.get("/api/v2/health")
        assert resp.status_code == 200

    @responses.activate
    def test_backend_error_relayed(self, app, monkeypatch):
        """Backend HTTP errors are relayed as-is to the browser."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            responses.GET,
            "http://mock-backend:8000/api/v2/account/profile",
            json={"detail": "Unauthorized"},
            status=401,
        )

        c = app.test_client()
        resp = c.get("/api/v2/account/profile")
        assert resp.status_code == 401


class TestProxyDisabled:
    """When USE_PROXY=False, /api/* returns 404."""

    def test_proxy_disabled_returns_404(self, app, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", False)
        c = app.test_client()
        resp = c.get("/api/v2/account/profile")
        assert resp.status_code == 404


class TestProxyMethods:
    """All HTTP methods are proxied."""

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
    @responses.activate
    def test_method_forwarded(self, app, monkeypatch, method):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            getattr(responses, method),
            "http://mock-backend:8000/api/v2/test",
            json={"method": method},
            status=200,
        )

        c = app.test_client()
        resp = getattr(c, method.lower())("/api/v2/test")
        assert resp.status_code == 200
