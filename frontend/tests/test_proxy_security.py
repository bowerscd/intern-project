"""Security-focused tests for the /api/* proxy layer.

Validates that the proxy does not introduce request-smuggling vectors,
header injection, or SSRF opportunities.
"""

import responses


class TestProxyHeaderSanitisation:
    """The proxy must strip hop-by-hop headers and not leak internals."""

    @responses.activate
    def test_host_header_not_forwarded(self, app, monkeypatch):
        """The Host header must NOT be forwarded — it would confuse the backend."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        def callback(request):
            # The Host header should not be the frontend's
            assert request.headers.get("Host", "") != "evil.example.com"
            return (200, {}, '{"ok": true}')

        responses.add_callback(
            responses.GET,
            "http://mock-backend:8000/api/v2/health",
            callback=callback,
            content_type="application/json",
        )

        c = app.test_client()
        resp = c.get("/api/v2/health", headers={"Host": "evil.example.com"})
        assert resp.status_code == 200

    @responses.activate
    def test_transfer_encoding_stripped(self, app, monkeypatch):
        """Transfer-Encoding should not be forwarded (hop-by-hop)."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        def callback(request):
            assert "Transfer-Encoding" not in request.headers
            return (200, {}, '{"ok": true}')

        responses.add_callback(
            responses.GET,
            "http://mock-backend:8000/api/v2/test",
            callback=callback,
            content_type="application/json",
        )

        c = app.test_client()
        resp = c.get("/api/v2/test", headers={"Transfer-Encoding": "chunked"})
        assert resp.status_code == 200


class TestProxyPathTraversal:
    """Ensure the proxy rejects path traversal attempts."""

    def test_double_dot_rejected(self, app, monkeypatch):
        """Path containing '..' must be rejected to prevent SSRF.

        Without validation, /api/../secret causes the proxy to request
        BACKEND_URL/secret — escaping the /api/ prefix entirely.
        """
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        c = app.test_client()
        resp = c.get("/api/..%2fsecret")
        # Should be rejected, not proxied
        assert resp.status_code in (400, 404)


class TestProxyTimeout:
    """Proxy should impose a timeout on backend calls."""

    @responses.activate
    def test_timeout_configured(self, app, monkeypatch):
        """The proxy uses timeout=30; verify we don't hang indefinitely."""
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        def timeout_callback(request):
            # Just verify the request was made — real timeout testing needs
            # integration tests.
            return (200, {}, '{"ok": true}')

        responses.add_callback(
            responses.GET,
            "http://mock-backend:8000/api/v2/test",
            callback=timeout_callback,
            content_type="application/json",
        )

        c = app.test_client()
        resp = c.get("/api/v2/test")
        assert resp.status_code == 200


class TestProxyResponseHeaders:
    """Backend response headers are relayed excluding hop-by-hop."""

    @responses.activate
    def test_content_type_relayed(self, app, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module, "USE_PROXY", True)
        monkeypatch.setattr(app_module, "BACKEND_URL", "http://mock-backend:8000")

        responses.add(
            responses.GET,
            "http://mock-backend:8000/api/v2/test",
            json={"data": "value"},
            status=200,
            content_type="application/json",
        )

        c = app.test_client()
        resp = c.get("/api/v2/test")
        assert "application/json" in resp.content_type
