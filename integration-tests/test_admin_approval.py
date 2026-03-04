"""Integration tests for admin account approval workflow.

Covers the end-to-end flow:
1. New account registration creates a PENDING_APPROVAL account
2. Pending account cannot log in (redirected to /login with error)
3. Admin can list pending accounts
4. Admin can approve/ban/defunct accounts
5. Approved account can log in normally
6. Admin role management (grant/revoke ADMIN claim)

These tests use live backend + OIDC server instances (no mocks).
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from helpers import (
    complete_registration as _complete_registration,
    create_backend_client as _create_backend_client,
    oidc_login as _oidc_login,
    oidc_register_session as _oidc_register_session,
    register_user as _register_user,
    rewrite_oidc_url as _rewrite_oidc_url,
)
from urllib.parse import urlparse, parse_qs, urlencode


# ---------------------------------------------------------------------------
# Helper: grant admin + activate via direct DB access
# ---------------------------------------------------------------------------

def _grant_admin_and_activate(db_path: str, username: str) -> None:
    """Set the ADMIN+BASIC claim bitmask (3) and status=active on an account."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE accounts SET claims = 3, status = 'active' WHERE username = ?",
            (username,),
        )
        conn.commit()
    finally:
        conn.close()


def _get_account_status(db_path: str, username: str) -> str | None:
    """Read an account's status from the DB."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT status FROM accounts WHERE username = ?",
            (username,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _oidc_login_session(
    backend_url: str,
    oidc_issuer: str,
    *,
    sub: str,
    name: str,
    email: str,
) -> httpx.Response:
    """Drive the OIDC login flow and return the callback response (no follow).

    Returns the response from the backend callback (could be 302 redirect
    or error).
    """
    client = _create_backend_client(backend_url)

    # 1. Initiate login
    resp = client.get("/api/v2/auth/login/test")
    assert resp.status_code in (302, 307)
    authorize_url = resp.headers["location"]

    # 2. Follow to OIDC authorize page
    authorize_url = _rewrite_oidc_url(authorize_url, oidc_issuer)
    resp = httpx.get(authorize_url, follow_redirects=False, timeout=10.0)
    assert resp.status_code == 200

    # 3. Approve the OIDC request
    parsed = urlparse(authorize_url)
    qs = parse_qs(parsed.query)
    approve_url = f"{oidc_issuer}/authorize/approve?" + urlencode(
        {
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub,
            "name": name,
            "email": email,
        }
    )
    resp = httpx.get(approve_url, follow_redirects=False, timeout=10.0)
    assert resp.status_code == 302

    # 4. Hit the backend callback (don't follow — we want to see the redirect)
    callback_url = resp.headers["location"]
    cb_parsed = urlparse(callback_url)
    callback_resp = client.get(f"{cb_parsed.path}?{cb_parsed.query}")

    return callback_resp


# ===========================================================================
# TestAdminApprovalWorkflow
# ===========================================================================


class TestRegistrationCreatesPendingAccount:
    """New account registration creates a PENDING_APPROVAL account."""

    def test_registration_returns_pending_status(
        self, backend_server, oidc_server
    ) -> None:
        """complete-registration response includes status=pending_approval."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-approval-reg-1",
            name="Pending User",
            email="pending-reg@test.local",
        )
        try:
            # Complete registration — should return pending status
            csrf_resp = client.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = client.post(
                "/api/v2/auth/complete-registration",
                json={"username": "pending_reg_user"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["status"] == "pending_approval"
            assert data["username"] == "pending_reg_user"
            assert "message" in data
        finally:
            client.close()

    def test_registration_does_not_establish_session(
        self, backend_server, oidc_server
    ) -> None:
        """After registration, the user has no authenticated session."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-approval-reg-2",
            name="No Session User",
            email="nosession-reg@test.local",
        )
        try:
            csrf_resp = client.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = client.post(
                "/api/v2/auth/complete-registration",
                json={"username": "nosession_reg_user"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 201

            # Try to access a protected endpoint — should fail
            resp = client.get("/api/v2/account/profile")
            assert resp.status_code == 401
        finally:
            client.close()


class TestPendingAccountCannotLogin:
    """A PENDING_APPROVAL account is rejected at the OIDC login callback."""

    def test_pending_account_redirected_to_login_with_error(
        self, backend_server, oidc_server
    ) -> None:
        """A pending account's login attempt redirects to /login?error=..."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # First register the account
        client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-approval-login-1",
            name="Pending Login User",
            email="pending-login@test.local",
        )
        try:
            csrf_resp = client.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = client.post(
                "/api/v2/auth/complete-registration",
                json={"username": "pending_login_user"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 201
        finally:
            client.close()

        # Now try to login — should be redirected
        resp = _oidc_login_session(
            backend_url, oidc_issuer,
            sub="admin-approval-login-1",
            name="Pending Login User",
            email="pending-login@test.local",
        )
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert "/login" in location
        assert "pending" in location.lower()


class TestAdminAccountEndpoints:
    """Admin account management API endpoints."""

    @staticmethod
    def _setup_admin(
        backend_url: str,
        oidc_issuer: str,
        db_path: str,
    ) -> httpx.Client:
        """Register (or find) an admin account and return an authenticated client.

        Handles the case where the admin user was already created by a
        previous test in the same session-scoped backend instance.
        """
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT id FROM accounts WHERE username = ?",
                ("admin_mgmt_user",),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            # First call: register the admin account
            reg_client = _oidc_register_session(
                backend_url, oidc_issuer,
                sub="admin-mgmt-admin",
                name="Admin User",
                email="admin-mgmt@test.local",
            )
            csrf_resp = reg_client.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            reg_client.post(
                "/api/v2/auth/complete-registration",
                json={"username": "admin_mgmt_user"},
                headers={"X-CSRF-Token": csrf},
            )
            reg_client.close()

        # Ensure admin is active with correct claims
        _grant_admin_and_activate(db_path, "admin_mgmt_user")

        # Login to get an authenticated session
        return _oidc_login(
            backend_url, oidc_issuer,
            sub="admin-mgmt-admin",
            name="Admin User",
            email="admin-mgmt@test.local",
        )

    def test_list_pending_accounts(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Admin can list accounts filtered by pending_approval status."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        admin = self._setup_admin(backend_url, oidc_issuer, backend_db_path)
        try:
            resp = admin.get(
                "/api/v2/account/admin/accounts?status_filter=pending_approval"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            # All returned accounts should have pending_approval status
            for acct in data:
                assert acct["status"] == "pending_approval"
        finally:
            admin.close()

    def test_approve_account(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Admin can approve a pending account, changing its status to active."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Register a pending account
        reg_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-approve-target-1",
            name="Approve Target",
            email="approve-target@test.local",
        )
        csrf_resp = reg_client.get("/api/v2/auth/csrf-token")
        csrf = csrf_resp.json()["csrf_token"]
        reg_resp = reg_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "approve_target_user"},
            headers={"X-CSRF-Token": csrf},
        )
        reg_client.close()
        assert reg_resp.status_code == 201
        target_id = reg_resp.json()["id"]

        # Admin approves
        admin = self._setup_admin(backend_url, oidc_issuer, backend_db_path)
        try:
            csrf_resp = admin.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = admin.post(
                f"/api/v2/account/admin/accounts/{target_id}/status",
                json={"status": "active"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "active"
        finally:
            admin.close()

        # Verify in DB
        status = _get_account_status(backend_db_path, "approve_target_user")
        assert status == "active"

    def test_ban_account(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Admin can ban an account."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Register a pending account
        reg_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-ban-target-1",
            name="Ban Target",
            email="ban-target@test.local",
        )
        csrf_resp = reg_client.get("/api/v2/auth/csrf-token")
        csrf = csrf_resp.json()["csrf_token"]
        reg_resp = reg_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "ban_target_user"},
            headers={"X-CSRF-Token": csrf},
        )
        reg_client.close()
        assert reg_resp.status_code == 201
        target_id = reg_resp.json()["id"]

        admin = self._setup_admin(backend_url, oidc_issuer, backend_db_path)
        try:
            csrf_resp = admin.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = admin.post(
                f"/api/v2/account/admin/accounts/{target_id}/status",
                json={"status": "banned"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "banned"
        finally:
            admin.close()

    def test_grant_revoke_admin_role(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Admin can grant and revoke ADMIN role on another account."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a target account
        reg_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-role-target-1",
            name="Role Target",
            email="role-target@test.local",
        )
        csrf_resp = reg_client.get("/api/v2/auth/csrf-token")
        csrf = csrf_resp.json()["csrf_token"]
        reg_resp = reg_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "role_target_user"},
            headers={"X-CSRF-Token": csrf},
        )
        reg_client.close()
        assert reg_resp.status_code == 201
        target_id = reg_resp.json()["id"]

        admin = self._setup_admin(backend_url, oidc_issuer, backend_db_path)
        try:
            # Grant ADMIN
            csrf_resp = admin.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = admin.post(
                f"/api/v2/account/admin/accounts/{target_id}/role",
                json={"grant_admin": True},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            assert resp.json()["claims"] & 2 != 0  # ADMIN bit

            # Revoke ADMIN
            csrf_resp = admin.get("/api/v2/auth/csrf-token")
            csrf = csrf_resp.json()["csrf_token"]
            resp = admin.post(
                f"/api/v2/account/admin/accounts/{target_id}/role",
                json={"grant_admin": False},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            assert resp.json()["claims"] & 2 == 0  # No ADMIN bit
        finally:
            admin.close()

    def test_admin_endpoints_require_auth(
        self, backend_server, oidc_server
    ) -> None:
        """Admin endpoints reject unauthenticated requests."""
        backend_url, _ = backend_server

        with _create_backend_client(backend_url) as client:
            # List accounts (GET → 401 from auth check)
            resp = client.get("/api/v2/account/admin/accounts")
            assert resp.status_code == 401

            # Update status (POST without CSRF → 403 from CSRF middleware)
            resp = client.post(
                "/api/v2/account/admin/accounts/1/status",
                json={"status": "active"},
            )
            assert resp.status_code in (401, 403)

            # Update role (POST without CSRF → 403 from CSRF middleware)
            resp = client.post(
                "/api/v2/account/admin/accounts/1/role",
                json={"grant_admin": True},
            )
            assert resp.status_code in (401, 403)


class TestApprovedAccountCanLogin:
    """After admin approval, the account can successfully log in."""

    def test_approved_account_login_succeeds(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Register → admin approves → login succeeds."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # 1. Register a new account (pending)
        reg_client = _oidc_register_session(
            backend_url, oidc_issuer,
            sub="admin-approval-e2e-1",
            name="E2E Approval User",
            email="e2e-approval@test.local",
        )
        csrf_resp = reg_client.get("/api/v2/auth/csrf-token")
        csrf = csrf_resp.json()["csrf_token"]
        reg_resp = reg_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "e2e_approval_user"},
            headers={"X-CSRF-Token": csrf},
        )
        reg_client.close()
        assert reg_resp.status_code == 201
        assert reg_resp.json()["status"] == "pending_approval"

        # 2. Admin approves via DB (simulating admin action)
        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "UPDATE accounts SET status = 'active' WHERE username = ?",
                ("e2e_approval_user",),
            )
            conn.commit()
        finally:
            conn.close()

        # 3. Login should now succeed (302 to the redirect, not /login?error=...)
        resp = _oidc_login_session(
            backend_url, oidc_issuer,
            sub="admin-approval-e2e-1",
            name="E2E Approval User",
            email="e2e-approval@test.local",
        )
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert "error" not in location, (
            f"Expected successful login redirect, got: {location}"
        )
