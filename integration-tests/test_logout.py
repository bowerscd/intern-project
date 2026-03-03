"""Integration tests for session logout.

Validates that ``POST /logout`` actually destroys the session so that
subsequent requests with the same cookie are treated as unauthenticated.
"""

import httpx

from helpers import register_user as _register_user


class TestLogoutInvalidatesSession:
    """Logging out should prevent reuse of the same session cookie."""

    def test_profile_fails_after_logout(
        self, backend_server, oidc_server
    ) -> None:
        """After POST /logout, GET /profile with the same cookie returns 401."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="logout-test-user", name="Logout User",
            email="logout@test.local", username="logout_test_user",
        )

        # Sanity: profile works before logout
        resp = client.get("/api/v2/account/profile")
        assert resp.status_code == 200

        # Logout
        csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = client.post(
            "/api/v2/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

        # Profile should now be rejected
        resp = client.get("/api/v2/account/profile")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 after logout, got {resp.status_code}"
        )

        client.close()

    def test_frontend_redirects_after_logout(
        self, frontend_server, backend_server, oidc_server
    ) -> None:
        """After logout, the frontend redirects to /login (no session cookie).

        The backend's logout response removes the session cookie, so the
        frontend's ``require_auth`` middleware detects its absence and
        redirects.
        """
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="logout-fe-user", name="Logout FE User",
            email="logout-fe@test.local", username="logout_fe_user",
        )

        # Extract the pre-logout session cookie for frontend verification
        session_cookie = None
        for cookie in client.cookies.jar:
            if "session" in cookie.name.lower():
                session_cookie = (cookie.name, cookie.value)
                break
        assert session_cookie is not None

        # Verify frontend works before logout
        with httpx.Client(
            base_url=frontend_url, follow_redirects=False, timeout=10.0
        ) as fe:
                fe.cookies.set(session_cookie[0], session_cookie[1])
                resp = fe.get("/account")
                assert resp.status_code == 200

        # Logout via backend
        csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = client.post(
            "/api/v2/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 200

        # Session cookie should be gone from the jar after logout
        remaining = [
            c.name for c in client.cookies.jar
            if "session" in c.name.lower()
        ]
        assert not remaining, f"Session cookie still present after logout: {remaining}"

        # Frontend should redirect (no cookie → /login)
        with httpx.Client(
            base_url=frontend_url, follow_redirects=False, timeout=10.0
        ) as fe:
            # Don't set any cookie — simulates a browser that honoured the
            # Set-Cookie deletion from the logout response.
            resp = fe.get("/account")
            assert resp.status_code == 302
            assert resp.headers["location"].endswith("/login")

        client.close()
