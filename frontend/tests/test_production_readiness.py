"""Tests for Flask frontend production-readiness features.

Covers: ProxyFix, health endpoint, error pages, request-ID, X-Forwarded-Proto.
"""


class TestProxyFix:
    """Verify ProxyFix middleware is wrapping the WSGI app."""

    def test_proxy_fix_applied(self) -> None:
        """The app.wsgi_app should be wrapped with ProxyFix."""
        from werkzeug.middleware.proxy_fix import ProxyFix
        import app as app_module

        assert isinstance(app_module.app.wsgi_app, ProxyFix)


class TestHealthEndpoint:
    """Verify the /healthz endpoint is accessible without auth."""

    def test_healthz_returns_200(self, client) -> None:
        """The health endpoint should return 200."""
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_returns_json(self, client) -> None:
        """The health endpoint should return JSON with status=ok."""
        resp = client.get("/healthz")
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_healthz_no_auth_required(self, unauthed_client) -> None:
        """The health endpoint should not require authentication."""
        resp = unauthed_client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_in_public_paths(self) -> None:
        """'/healthz' should be in PUBLIC_PATHS."""
        import app as app_module

        assert "/healthz" in app_module.PUBLIC_PATHS


class TestRequestID:
    """Verify request ID generation and propagation."""

    def test_response_has_request_id(self, client) -> None:
        """Every response should contain an X-Request-ID header."""
        resp = client.get("/healthz")
        assert "X-Request-ID" in resp.headers

    def test_request_id_propagated(self, client) -> None:
        """A provided X-Request-ID should be echoed back."""
        resp = client.get("/healthz", headers={"X-Request-ID": "test-trace-123"})
        assert resp.headers.get("X-Request-ID") == "test-trace-123"


class TestErrorPages:
    """Verify custom error pages are registered."""

    def test_404_returns_html(self, mock_client) -> None:
        """A missing page should return a custom 404 with HTML content."""
        resp = mock_client.get("/this-page-does-not-exist")
        assert resp.status_code == 404
        assert b"404" in resp.data

    def test_404_returns_json_when_requested(self, mock_client) -> None:
        """404 should return JSON when Accept: application/json."""
        resp = mock_client.get(
            "/this-page-does-not-exist",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["detail"] == "Not found"


class TestXForwardedProto:
    """Verify X-Forwarded-Proto is forwarded in the proxy."""

    def test_forwarded_proto_is_forwarded(self, mock_client, monkeypatch) -> None:
        """The proxy should forward X-Forwarded-Proto from the incoming request."""
        import app as app_module
        from unittest.mock import MagicMock

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "USE_MOCK", True)

        captured_kwargs: dict = {}

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b'{"ok": true}'
        fake_resp.raw.headers = {"Content-Type": "application/json"}

        def capture_request(**kwargs):
            captured_kwargs.update(kwargs)
            return fake_resp

        monkeypatch.setattr(
            app_module, "http_requests", MagicMock(request=capture_request)
        )

        mock_client.get("/api/v2/healthz")

        headers_sent = captured_kwargs.get("headers", {})
        assert "X-Forwarded-Proto" in headers_sent
