"""Integration tests for the admin claim-approval workflow.

Exercises the full lifecycle:
  1. Register via OIDC (creates a session with ``pending_registration``)
  2. Submit an account claim for a legacy user
  3. Authenticate as an admin
  4. List pending claims
  5. Approve (or deny) the claim
  6. Verify the claimant can now log in as the legacy account
"""

import httpx
import pytest

from helpers import oidc_register_session as _oidc_register_session
from helpers import complete_registration as _complete_registration


class TestAdminClaimApproval:
    """End-to-end test for submitting and approving an account claim."""

    def test_full_claim_approve_flow(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """An admin approves a claim and the legacy account is linked to the claimant."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # ── Step 1: Create an admin account via OIDC ──

        admin_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-claim-test", name="Admin User", email="admin@test.local",
        )
        admin_data = _complete_registration(admin_client, "claim_admin_user")

        import sqlite3

        conn = sqlite3.connect(backend_db_path)
        try:
            # BASIC=1, ADMIN=2 → 3 means both
            conn.execute(
                "UPDATE accounts SET claims = 3 WHERE username = ?",
                ("claim_admin_user",),
            )
            conn.commit()
        finally:
            conn.close()

        # Verify the admin now has ADMIN claim
        resp = admin_client.get("/api/v2/account/profile")
        assert resp.status_code == 200
        profile = resp.json()
        assert profile["claims"] & 2 == 2, f"Admin claim not set: claims={profile['claims']}"

        # ── Step 2: Create a legacy account (seed directly via SQL) ──

        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "INSERT INTO accounts (username, email, phone, phone_provider, "
                "account_provider, external_unique_id, claims) "
                "VALUES (?, ?, NULL, 1, 1, 'legacy-placeholder', 1)",
                ("legacy_claim_target", "legacy@test.local"),
            )
            conn.commit()
        finally:
            conn.close()

        # ── Step 3: A new user registers and claims the legacy account ──

        claimant_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="claimant-user-1", name="Claimant User", email="claimant@test.local",
        )

        claimant_csrf = claimant_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = claimant_client.post(
            "/api/v2/auth/claim-account",
            json={"username": "legacy_claim_target"},
            headers={"X-CSRF-Token": claimant_csrf},
        )
        assert resp.status_code == 202, resp.text[:500]
        claim_data = resp.json()
        assert claim_data["status"] == "pending"
        claim_id = claim_data["claim_id"]

        # ── Step 4: Admin lists pending claims ──

        resp = admin_client.get("/api/v2/account/admin/claims")
        assert resp.status_code == 200
        claims_list = resp.json()
        assert any(c["id"] == claim_id for c in claims_list), (
            f"Claim {claim_id} not in pending list: {claims_list}"
        )

        pending_claim = next(c for c in claims_list if c["id"] == claim_id)
        assert pending_claim["status"] == "pending"
        assert pending_claim["target_username"] == "legacy_claim_target"
        assert pending_claim["requester_name"] == "Claimant User"

        # ── Step 5: Admin approves the claim ──

        admin_csrf = admin_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = admin_client.post(
            f"/api/v2/account/admin/claims/{claim_id}/review",
            json={"decision": "approve"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert resp.status_code == 200, resp.text[:500]
        result = resp.json()
        assert result["status"] == "approved"
        assert result["resolved_at"] is not None

        # ── Step 6: Verify the legacy account now has the claimant's OIDC identity ──

        conn = sqlite3.connect(backend_db_path)
        try:
            row = conn.execute(
                "SELECT account_provider, external_unique_id FROM accounts WHERE username = ?",
                ("legacy_claim_target",),
            ).fetchone()
            assert row is not None
            # ExternalAuthProvider.test.value == 1 (stored as integer by SqlValueEnum)
            assert row[0] == 1, f"Expected provider=1 (test), got {row[0]!r}"
            assert row[1] == "claimant-user-1"
        finally:
            conn.close()

        # ── Step 7: Pending list is now empty ──

        resp = admin_client.get("/api/v2/account/admin/claims")
        assert resp.status_code == 200
        remaining = resp.json()
        assert not any(c["id"] == claim_id for c in remaining)

        # Clean up clients
        claimant_client.close()
        admin_client.close()

    def test_deny_claim_flow(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """An admin denies a claim and the legacy account is NOT linked."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        import sqlite3

        # ── Create admin account ──

        admin_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-deny-test", name="Deny Admin", email="deny-admin@test.local",
        )
        _complete_registration(admin_client, "deny_admin_user")

        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "UPDATE accounts SET claims = 3 WHERE username = ?",
                ("deny_admin_user",),
            )
            conn.commit()
        finally:
            conn.close()

        # ── Create legacy account ──

        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "INSERT INTO accounts (username, email, phone, phone_provider, "
                "account_provider, external_unique_id, claims) "
                "VALUES (?, ?, NULL, 1, 1, 'deny-legacy-placeholder', 1)",
                ("deny_legacy_target", "deny-legacy@test.local"),
            )
            conn.commit()
        finally:
            conn.close()

        # ── Claimant submits a claim ──

        claimant_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="deny-claimant-1", name="Deny Claimant", email="deny-claimant@test.local",
        )

        claimant_csrf = claimant_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = claimant_client.post(
            "/api/v2/auth/claim-account",
            json={"username": "deny_legacy_target"},
            headers={"X-CSRF-Token": claimant_csrf},
        )
        assert resp.status_code == 202
        claim_id = resp.json()["claim_id"]

        # ── Admin denies the claim ──

        admin_csrf = admin_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = admin_client.post(
            f"/api/v2/account/admin/claims/{claim_id}/review",
            json={"decision": "deny"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "denied"

        # ── Verify legacy account was NOT updated ──

        conn = sqlite3.connect(backend_db_path)
        try:
            row = conn.execute(
                "SELECT external_unique_id FROM accounts WHERE username = ?",
                ("deny_legacy_target",),
            ).fetchone()
            assert row[0] == "deny-legacy-placeholder", (
                "Legacy account should not be modified after denial"
            )
        finally:
            conn.close()

        claimant_client.close()
        admin_client.close()

    def test_non_admin_cannot_list_claims(
        self, backend_server, oidc_server
    ) -> None:
        """A non-admin user is rejected with 403 when accessing admin endpoints."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Register a normal (non-admin) user
        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="non-admin-claim-test", name="Normal User", email="normal@test.local",
        )
        _complete_registration(client, "normal_claim_user")

        resp = client.get("/api/v2/account/admin/claims")
        assert resp.status_code == 403

        client.close()

    def test_double_approve_returns_conflict(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Approving an already-approved claim returns 409."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        import sqlite3

        # Create admin
        admin_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-double-test", name="Double Admin", email="double-admin@test.local",
        )
        _complete_registration(admin_client, "double_admin_user")

        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "UPDATE accounts SET claims = 3 WHERE username = ?",
                ("double_admin_user",),
            )
            conn.commit()
        finally:
            conn.close()

        # Create legacy account
        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "INSERT INTO accounts (username, email, phone, phone_provider, "
                "account_provider, external_unique_id, claims) "
                "VALUES (?, ?, NULL, 1, 1, 'double-legacy-ph', 1)",
                ("double_legacy_target", "double-legacy@test.local"),
            )
            conn.commit()
        finally:
            conn.close()

        # Claimant submits claim
        claimant_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="double-claimant-1", name="Double Claimant", email="double-claimant@test.local",
        )
        claimant_csrf = claimant_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = claimant_client.post(
            "/api/v2/auth/claim-account",
            json={"username": "double_legacy_target"},
            headers={"X-CSRF-Token": claimant_csrf},
        )
        assert resp.status_code == 202
        claim_id = resp.json()["claim_id"]

        # Admin approves
        admin_csrf = admin_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = admin_client.post(
            f"/api/v2/account/admin/claims/{claim_id}/review",
            json={"decision": "approve"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert resp.status_code == 200

        # Try to approve again → 409
        admin_csrf = admin_client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = admin_client.post(
            f"/api/v2/account/admin/claims/{claim_id}/review",
            json={"decision": "approve"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert resp.status_code == 409

        claimant_client.close()
        admin_client.close()
