"""Integration tests for CSRF enforcement on mutation endpoints.

Verifies that every state-changing POST endpoint rejects requests that
omit or send an incorrect ``X-CSRF-Token`` header.
"""

import httpx
import sqlite3

from helpers import oidc_register_session as _oidc_register_session
from helpers import complete_registration as _complete_registration
from helpers import activate_account, oidc_login


class TestCSRFEnforcementCompleteRegistration:
    """POST /complete-registration must require a valid CSRF token."""

    def test_missing_csrf_rejected(
        self, backend_server, oidc_server
    ) -> None:
        """Omitting X-CSRF-Token header returns 403."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="csrf-reg-missing", name="CSRF Missing",
            email="csrf-reg-missing@test.local",
        )

        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "csrf_missing_user"},
            # No X-CSRF-Token header
        )
        assert resp.status_code == 403, (
            f"Expected 403 without CSRF, got {resp.status_code}"
        )
        client.close()

    def test_wrong_csrf_rejected(
        self, backend_server, oidc_server
    ) -> None:
        """A fabricated X-CSRF-Token should be rejected."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="csrf-reg-wrong", name="CSRF Wrong",
            email="csrf-reg-wrong@test.local",
        )

        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "csrf_wrong_user"},
            headers={"X-CSRF-Token": "definitely-not-a-valid-token"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 with bad CSRF, got {resp.status_code}"
        )
        client.close()


class TestCSRFEnforcementClaimAccount:
    """POST /claim-account must require a valid CSRF token."""

    def test_missing_csrf_rejected(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Omitting X-CSRF-Token on claim-account returns 403."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Seed a legacy account to claim
        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO accounts "
                "(username, email, phone, phone_provider, account_provider, "
                "external_unique_id, claims) "
                "VALUES (?, ?, NULL, 1, 1, 'csrf-claim-legacy', 1)",
                ("csrf_claim_target", "csrf-claim@test.local"),
            )
            conn.commit()
        finally:
            conn.close()

        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="csrf-claim-user", name="CSRF Claim",
            email="csrf-claim-user@test.local",
        )

        resp = client.post(
            "/api/v2/auth/claim-account",
            json={"username": "csrf_claim_target"},
            # No CSRF token
        )
        assert resp.status_code == 403, (
            f"Expected 403 without CSRF on claim-account, got {resp.status_code}"
        )
        client.close()


class TestCSRFEnforcementLogout:
    """POST /logout must require a valid CSRF token."""

    def test_missing_csrf_rejected(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Omitting X-CSRF-Token on logout returns 403."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="csrf-logout-user", name="CSRF Logout",
            email="csrf-logout@test.local",
        )
        _complete_registration(client, "csrf_logout_user")
        client.close()

        # Account is pending_approval after registration; activate then login
        activate_account(backend_db_path, "csrf_logout_user")
        client = oidc_login(
            backend_url, oidc_issuer,
            sub="csrf-logout-user", name="CSRF Logout",
            email="csrf-logout@test.local",
        )

        resp = client.post("/api/v2/auth/logout")
        assert resp.status_code == 403, (
            f"Expected 403 without CSRF on logout, got {resp.status_code}"
        )
        client.close()


class TestCSRFEnforcementAdminReview:
    """POST /admin/claims/{id}/review must require a valid CSRF token."""

    def test_missing_csrf_rejected(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Omitting X-CSRF-Token on admin review returns 403."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create an admin
        admin = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="csrf-admin-review", name="CSRF Admin",
            email="csrf-admin@test.local",
        )
        _complete_registration(admin, "csrf_admin_review_user")
        admin.close()

        # Activate account and grant admin claims
        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "UPDATE accounts SET status = 'active', claims = 3 "
                "WHERE username = ?",
                ("csrf_admin_review_user",),
            )
            conn.commit()
        finally:
            conn.close()

        # Re-login to get an authenticated session
        admin = oidc_login(
            backend_url, oidc_issuer,
            sub="csrf-admin-review", name="CSRF Admin",
            email="csrf-admin@test.local",
        )

        resp = admin.post(
            "/api/v2/account/admin/claims/999/review",
            json={"decision": "deny"},
            # No CSRF token
        )
        assert resp.status_code == 403, (
            f"Expected 403 without CSRF on admin review, got {resp.status_code}"
        )
        admin.close()
