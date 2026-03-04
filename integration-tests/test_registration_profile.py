"""Integration tests for end-to-end registration → profile round-trip.

Validates that every field submitted during OIDC registration is correctly
persisted and returned by the profile endpoint.
"""

import httpx

from helpers import oidc_register_session, complete_registration, activate_account, oidc_login


class TestRegistrationProfile:
    """Register a new user and verify the profile endpoint returns correct data."""

    def test_profile_matches_registration(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Profile should reflect the OIDC identity and chosen username."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = oidc_register_session(
            backend_url, oidc_issuer,
            sub="profile-round-trip-user",
            name="Profile Roundtrip",
            email="profile-rt@test.local",
        )

        reg_data = complete_registration(client, "profile_roundtrip_user")
        assert reg_data["username"] == "profile_roundtrip_user"
        client.close()

        # Account is pending_approval after registration; activate and re-login
        activate_account(backend_db_path, "profile_roundtrip_user")
        client = oidc_login(
            backend_url, oidc_issuer,
            sub="profile-round-trip-user",
            name="Profile Roundtrip",
            email="profile-rt@test.local",
        )

        # ── Verify profile ──
        resp = client.get("/api/v2/account/profile")
        assert resp.status_code == 200
        profile = resp.json()

        assert profile["username"] == "profile_roundtrip_user"
        # BASIC claim should be set automatically on registration
        assert profile["claims"] & 1 == 1, (
            f"BASIC claim not set: claims={profile['claims']}"
        )

        client.close()

    def test_duplicate_username_rejected(
        self, backend_server, oidc_server
    ) -> None:
        """Attempting to register with an already-taken username returns 409."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # First user registers successfully
        c1 = oidc_register_session(
            backend_url, oidc_issuer,
            sub="dup-user-1", name="Dup User 1", email="dup1@test.local",
        )
        complete_registration(c1, "unique_dup_test_user")

        # Second user tries the same username
        c2 = oidc_register_session(
            backend_url, oidc_issuer,
            sub="dup-user-2", name="Dup User 2", email="dup2@test.local",
        )

        csrf = c2.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = c2.post(
            "/api/v2/auth/complete-registration",
            json={"username": "unique_dup_test_user"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 409, (
            f"Expected 409 for duplicate username, got {resp.status_code}: {resp.text[:300]}"
        )

        c1.close()
        c2.close()
