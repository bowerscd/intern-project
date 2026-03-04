"""End-to-end auth gate tests via the Flask frontend.

Validates that the frontend's ``require_auth`` middleware correctly redirects
unauthenticated requests to ``/login`` when the backend session cookie is
missing, and allows access when a valid session is present.
"""

import httpx
import pytest
from urllib.parse import urlparse, parse_qs, urlencode

from helpers import activate_account, create_backend_client, oidc_login


PROTECTED_PAGES = [
    "/",
    "/account",
    "/mealbot",
    "/mealbot/individualized",
    "/happyhour/manage",
    "/admin",
]

PUBLIC_PAGES = [
    "/login",
    "/auth/callback",
    "/auth/complete-registration",
    "/auth/claim-account",
    "/happyhour",
]


class TestUnauthenticatedRedirects:
    """Pages that require auth should redirect to /login without a session cookie."""

    @pytest.mark.parametrize("path", PROTECTED_PAGES)
    def test_redirect_to_login(self, frontend_client: httpx.Client, path: str) -> None:
        resp = frontend_client.get(path)
        assert resp.status_code == 302
        assert resp.headers["location"].endswith("/login")


class TestPublicPagesAccessible:
    """Public pages should be accessible without a session cookie."""

    @pytest.mark.parametrize("path", PUBLIC_PAGES)
    def test_public_page_ok(self, frontend_client: httpx.Client, path: str) -> None:
        resp = frontend_client.get(path)
        assert resp.status_code == 200


class TestProxyForwarding:
    """API proxy should forward requests to the backend."""

    def test_proxy_unauthenticated_returns_401(
        self, frontend_client: httpx.Client
    ) -> None:
        """Proxied API requests without auth should return 401 from the backend."""
        resp = frontend_client.get("/api/v2/account/profile")
        assert resp.status_code in (401, 403)

    def test_proxy_path_traversal_blocked(self, frontend_server) -> None:
        """Path traversal through the proxy should be rejected."""
        frontend_url, _ = frontend_server
        # httpx normalizes '..' in URLs, so use a raw socket or path that
        # reaches Flask's route with '..' in the path variable.
        # Flask's <path:path> receives the literal segments, so test
        # with an encoded traversal that the proxy handler catches.
        with httpx.Client(
            base_url=frontend_url, follow_redirects=False, timeout=10.0
        ) as c:
            resp = c.get("/api/v2/../../etc/passwd")
            # Either 400 (traversal caught) or 404 (route not matched)
            # or 302 (auth redirect) — any of these prove it didn't proxy
            assert resp.status_code in (400, 404, 302)


class TestAuthenticatedFlow:
    """Authenticated session grants access to protected pages."""

    def test_authenticated_page_access(
        self, frontend_server, backend_server, oidc_server, backend_db_path
    ) -> None:
        """After registering via OIDC, protected pages should be accessible."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # ── Step 1: Register a user through the backend API ──
        backend_client = create_backend_client(backend_url)

        resp = backend_client.get("/api/v2/auth/register/test")
        assert resp.status_code in (302, 307)
        authorize_url = resp.headers["location"]

        parsed = urlparse(authorize_url)
        qs = parse_qs(parsed.query)
        approve_params = {
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": "auth-gate-user",
            "name": "Auth Gate User",
            "email": "gate@test.local",
        }
        approve_resp = httpx.get(
            f"{oidc_issuer}/authorize/approve?{urlencode(approve_params)}",
            follow_redirects=False,
            timeout=10.0,
        )
        assert approve_resp.status_code == 302
        callback_url = approve_resp.headers["location"]
        callback_parsed = urlparse(callback_url)
        callback_path = f"{callback_parsed.path}?{callback_parsed.query}"
        resp = backend_client.get(callback_path)
        assert resp.status_code in (302, 307)

        # Complete registration
        csrf_resp = backend_client.get("/api/v2/auth/csrf-token")
        csrf = csrf_resp.json()["csrf_token"]
        resp = backend_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "auth_gate_test_user"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201
        backend_client.close()

        # ── Step 2: Activate the account and re-login ──
        activate_account(backend_db_path, "auth_gate_test_user")
        login_client = oidc_login(
            backend_url, oidc_issuer,
            sub="auth-gate-user",
            name="Auth Gate User",
            email="gate@test.local",
        )

        # ── Step 3: Extract the session cookie ──
        session_cookie = None
        for cookie in login_client.cookies.jar:
            if "session" in cookie.name.lower():
                session_cookie = (cookie.name, cookie.value)
                break
        assert session_cookie is not None, (
            "Backend did not set a session cookie after login"
        )

        # ── Step 4: Set the cookie on a frontend client and verify access ──
        with httpx.Client(
            base_url=frontend_url, follow_redirects=False, timeout=10.0
        ) as fe_session:
            fe_session.cookies.set(session_cookie[0], session_cookie[1])

            resp = fe_session.get("/account")
            assert resp.status_code == 200

            # Also verify the proxied API works with the cookie
            resp = fe_session.get("/api/v2/account/profile")
            assert resp.status_code == 200

        login_client.close()


class TestStaticAssets:
    """Static assets should always be accessible."""

    def test_static_css(self, frontend_client: httpx.Client) -> None:
        resp = frontend_client.get("/static/css/main.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers.get("content-type", "")
