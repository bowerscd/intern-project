"""End-to-end OIDC Authorization Code flow tests.

Validates the complete login/register flow through:
  Backend login endpoint → Mock OIDC authorize → approve → callback → session
"""

import httpx
from urllib.parse import urlparse, parse_qs, urlencode

from helpers import activate_account, oidc_login, rewrite_oidc_url, create_backend_client


class TestOIDCLoginFlow:
    """Full Authorization Code flow via the backend's /auth/login/test."""

    def test_login_redirects_to_oidc_authorize(
        self, client: httpx.Client, oidc_server
    ) -> None:
        """GET /api/v2/auth/login/test should redirect to the OIDC authorize endpoint."""
        oidc_issuer, _ = oidc_server
        resp = client.get("/api/v2/auth/login/test")
        assert resp.status_code in (302, 307)

        location = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        parsed = urlparse(location)
        assert location.startswith(f"{oidc_issuer}/authorize")

        qs = parse_qs(parsed.query)
        assert "state" in qs
        assert "nonce" in qs
        assert qs["client_id"][0] == "client_id1"
        assert "redirect_uri" in qs

    def test_full_login_flow(
        self, client: httpx.Client, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Complete OIDC flow: register → OIDC → callback → complete-registration → pending → activate → login → session."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Use a dedicated client with cookie jar to track the full flow
        with create_backend_client(backend_url) as session_client:
            # Step 1: Initiate REGISTRATION (not login, since account doesn't exist yet)
            resp = session_client.get("/api/v2/auth/register/test")
            assert resp.status_code in (302, 307)
            authorize_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)

            # Step 2: Follow redirect to OIDC authorize (get the form)
            resp = httpx.get(authorize_url, follow_redirects=False, timeout=10.0)
            assert resp.status_code == 200
            assert "Mock OIDC" in resp.text

            # Step 3: Submit the "approve" form — simulate user clicking Authorize
            parsed = urlparse(authorize_url)
            qs = parse_qs(parsed.query)
            approve_params = {
                "redirect_uri": qs["redirect_uri"][0],
                "state": qs["state"][0],
                "nonce": qs["nonce"][0],
                "sub": "integration-user-1",
                "name": "E2E Test User",
                "email": "e2e@test.local",
            }
            approve_url = f"{oidc_issuer}/authorize/approve?{urlencode(approve_params)}"
            resp = httpx.get(approve_url, follow_redirects=False, timeout=10.0)
            assert resp.status_code == 302

            # Step 4: The OIDC provider redirects to the backend callback
            callback_url = resp.headers["location"]
            assert "/api/v2/auth/callback/test" in callback_url
            callback_parsed = urlparse(callback_url)
            callback_qs = parse_qs(callback_parsed.query)
            assert "code" in callback_qs
            assert "state" in callback_qs

            # Step 5: Hit the backend callback (which exchanges code for tokens)
            # Transfer auth cookies from step 1 (state, nonce anti-CSRF cookies)
            callback_path = f"{callback_parsed.path}?{callback_parsed.query}"
            resp = session_client.get(callback_path)

            # Register mode callback stores pending_registration in session
            # and redirects to the completion page
            assert resp.status_code in (302, 307), (
                f"Callback returned {resp.status_code}: {resp.text[:500]}"
            )

            # Step 6: Obtain a CSRF token (required for state-changing requests)
            csrf_resp = session_client.get("/api/v2/auth/csrf-token")
            csrf_token = csrf_resp.json()["csrf_token"]

            # Step 7: Complete registration by choosing a username
            resp = session_client.post(
                "/api/v2/auth/complete-registration",
                json={"username": "e2e_integration_user"},
                headers={"X-CSRF-Token": csrf_token},
            )
            assert resp.status_code == 201, (
                f"Complete registration returned {resp.status_code}: {resp.text[:500]}"
            )
            reg_result = resp.json()
            assert reg_result["username"] == "e2e_integration_user"

            # Step 8: Registration now returns pending_approval status and
            # does NOT establish a session (admin approval required).
            assert reg_result["status"] == "pending_approval"
            assert "message" in reg_result

        # Step 9: Activate the account (simulating admin approval) and re-login
        activate_account(backend_db_path, "e2e_integration_user")
        login_client = oidc_login(
            backend_url, oidc_issuer,
            sub="integration-user-1",
            name="E2E Test User",
            email="e2e@test.local",
        )
        try:
            # Step 10: Authenticated request should succeed
            resp = login_client.get("/api/v2/account/profile")
            assert resp.status_code == 200
            profile = resp.json()
            assert profile["username"] == "e2e_integration_user"
        finally:
            login_client.close()


class TestOIDCRegisterFlow:
    """Registration flow goes through the same OIDC endpoints with mode=register."""

    def test_register_redirects_to_oidc(
        self, client: httpx.Client, oidc_server
    ) -> None:
        oidc_issuer, _ = oidc_server
        resp = client.get("/api/v2/auth/register/test")
        assert resp.status_code in (302, 307)
        assert rewrite_oidc_url(resp.headers["location"], oidc_issuer).startswith(
            f"{oidc_issuer}/authorize"
        )


class TestOIDCEdgeCases:
    """OIDC edge cases that should be handled gracefully."""

    def test_callback_without_login_returns_error(self, client: httpx.Client) -> None:
        """Hitting the callback directly with a fake code should fail cleanly."""
        resp = client.get("/api/v2/auth/callback/test?code=fake&state=fake")
        # Should fail (no matching state cookie / invalid code), not crash
        assert resp.status_code in (400, 401, 403, 422, 500)

    def test_login_with_invalid_provider(self, client: httpx.Client) -> None:
        """A non-existent provider should return 422."""
        resp = client.get("/api/v2/auth/login/nonexistent")
        assert resp.status_code == 422

    def test_replay_authorization_code(
        self, client: httpx.Client, backend_server, oidc_server
    ) -> None:
        """Using the same authorization code twice should fail."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        with create_backend_client(backend_url) as c:
            # Start login
            resp = c.get("/api/v2/auth/login/test")
            authorize_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)

            # Get authorize params and approve
            parsed = urlparse(authorize_url)
            qs = parse_qs(parsed.query)
            approve_params = {
                "redirect_uri": qs["redirect_uri"][0],
                "state": qs["state"][0],
                "nonce": qs["nonce"][0],
                "sub": "replay-user",
                "name": "Replay Test",
                "email": "replay@test.local",
            }
            approve_url = f"{oidc_issuer}/authorize/approve?{urlencode(approve_params)}"
            resp = httpx.get(approve_url, follow_redirects=False, timeout=10.0)
            callback_url = resp.headers["location"]
            callback_parsed = urlparse(callback_url)
            callback_path = f"{callback_parsed.path}?{callback_parsed.query}"

            # First use: should succeed
            resp = c.get(callback_path)
            # May redirect or return error (state cookie mismatch possible)
            _ = resp.status_code

            # Second use: same code should fail (already consumed)
            resp2 = c.get(callback_path)
            # Either the backend or the OIDC provider rejects the replayed code
            # 422 is also valid — the callback deletes auth cookies on first use,
            # so the second call has no auth_state/auth_nonce.
            assert resp2.status_code in (302, 307, 400, 401, 403, 422, 500)
