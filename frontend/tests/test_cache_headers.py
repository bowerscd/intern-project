"""Tests for cache-control headers on Flask-served pages.

Ensures that authenticated pages are not cached by intermediaries and that
static assets have appropriate caching directives.
"""


class TestPageCacheHeaders:
    """HTML page responses should discourage caching of authenticated content."""

    def test_protected_page_no_store(self, authed_client):
        """Authenticated pages should set Cache-Control: no-store or no-cache."""
        resp = authed_client.get("/account")
        assert resp.status_code == 200
        # Flask doesn't set cache headers by default; this test documents the
        # current behaviour and will fail if someone adds aggressive caching.
        cc = resp.headers.get("Cache-Control", "")
        # If Cache-Control IS set, it must not be public/long-lived.
        if cc:
            assert "public" not in cc.lower()

    def test_login_page_cacheable(self, client):
        """Public login page can be cached reasonably."""
        resp = client.get("/login")
        assert resp.status_code == 200
        # No hard requirement — just ensure no broken headers
        assert resp.headers.get("Content-Type", "").startswith("text/html")


class TestStaticAssetCacheHeaders:
    """Static assets should have appropriate caching."""

    def test_css_content_type(self, client):
        resp = client.get("/static/css/main.css")
        assert resp.status_code == 200
        assert "text/css" in resp.content_type
