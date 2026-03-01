"""Security integration tests.

Tests that require a running backend + OIDC to validate security properties
that can't be tested in isolation.
"""

import httpx
import pytest
from urllib.parse import urlparse, parse_qs


class TestXSSPrevention:
    """HTML responses should not reflect user input unsanitised."""

    def test_404_does_not_reflect_path(self, client: httpx.Client) -> None:
        """A crafted 404 path should not be echoed back in the response body."""
        payload = "<script>alert(1)</script>"
        resp = client.get(f"/api/v2/{payload}")
        body = resp.text
        assert payload not in body, "XSS payload reflected in 404 response"

    def test_error_does_not_reflect_query(self, client: httpx.Client) -> None:
        """Error responses should not reflect query parameters verbatim."""
        payload = '<img src=x onerror="alert(1)">'
        resp = client.get(f"/api/v2/account/profile?evil={payload}")
        body = resp.text
        assert payload not in body


class TestSessionSecurity:
    """Session cookie properties in a running environment."""

    def test_session_cookie_httponly(
        self, backend_server, oidc_server
    ) -> None:
        """The session cookie set after OIDC callback must be HttpOnly."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        with httpx.Client(
            base_url=backend_url, follow_redirects=False, timeout=10.0
        ) as c:
            # Go through the OIDC flow
            resp = c.get("/api/v2/auth/login/test")
            if resp.status_code not in (302, 307):
                pytest.skip("Login did not redirect")

            authorize_url = resp.headers["location"]
            parsed = urlparse(authorize_url)
            qs = parse_qs(parsed.query)

            from urllib.parse import urlencode
            approve_params = {
                "redirect_uri": qs["redirect_uri"][0],
                "state": qs["state"][0],
                "nonce": qs["nonce"][0],
                "sub": "session-security-user",
                "name": "Session User",
                "email": "session@test.local",
            }
            approve_resp = httpx.get(
                f"{oidc_issuer}/authorize/approve?{urlencode(approve_params)}",
                follow_redirects=False,
                timeout=10.0,
            )
            callback_url = approve_resp.headers["location"]
            callback_parsed = urlparse(callback_url)
            callback_path = f"{callback_parsed.path}?{callback_parsed.query}"

            resp = c.get(callback_path)

            # Check Set-Cookie headers for HttpOnly
            set_cookie_headers = resp.headers.get_list("set-cookie") if hasattr(
                resp.headers, "get_list"
            ) else [
                v for k, v in resp.headers.multi_items()
                if k.lower() == "set-cookie"
            ]

            session_cookies = [
                h for h in set_cookie_headers if "session" in h.lower()
            ]
            for cookie_header in session_cookies:
                assert "httponly" in cookie_header.lower(), (
                    f"Session cookie missing HttpOnly: {cookie_header}"
                )


class TestCSRFProtection:
    """OIDC state parameter prevents CSRF on the callback."""

    def test_callback_wrong_state_rejected(self, client: httpx.Client) -> None:
        """A callback with a mismatched state parameter should fail."""
        resp = client.get("/api/v2/auth/callback/test?code=fake&state=wrong")
        # Without a matching anti-CSRF state cookie, this must fail
        assert resp.status_code in (400, 401, 403, 422, 500)


class TestCORSIntegration:
    """CORS headers on the running backend."""

    def test_preflight_from_allowed_origin(self, client: httpx.Client) -> None:
        """An OPTIONS preflight from an allowed origin should succeed."""
        resp = client.request(
            "OPTIONS",
            "/api/v2/account/profile",
            headers={
                "Origin": "http://127.0.0.1",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200


class TestAPIResponseSecurity:
    """Security-related response headers from the backend."""

    def test_json_content_type(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/account/profile")
        # Even a 401 should be JSON
        assert "application/json" in resp.headers.get("content-type", "")

    def test_no_server_version(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/account/profile")
        server_header = resp.headers.get("server", "").lower()
        # Should not leak specific version numbers
        assert "uvicorn" not in server_header or "." not in server_header
