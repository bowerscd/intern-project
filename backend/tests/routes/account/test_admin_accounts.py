"""Tests for admin account management endpoints.

Covers:
- ``GET /api/v2/account/admin/accounts`` — list all accounts with optional filter
- ``POST /api/v2/account/admin/accounts/{id}/status`` — approve, ban, defunct
- ``POST /api/v2/account/admin/accounts/{id}/role`` — grant/revoke admin
- Account status gates on login callback and RequireLogin dependency
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from http.cookiejar import Cookie

from app import app
from db import Database
from db.functions import create_account
from models import AccountClaims, AccountStatus, ExternalAuthProvider
from routes.shared import AUTH_SESSION_KEY


# ── Helpers ───────────────────────────────────────────────────────────


def _mk_auth_cookie(secret: Any, account_id: int) -> Cookie:
    """Build a signed session cookie for the test client."""
    from json import dumps
    from base64 import b64encode
    from itsdangerous import TimestampSigner
    from datetime import datetime, UTC, timedelta
    from routes import SESSION_COOKIE_NAME

    signer = TimestampSigner(secret_key=str(secret))
    signed = signer.sign(
        b64encode(dumps({AUTH_SESSION_KEY: account_id}).encode("utf-8"))
    ).decode("utf-8")
    return Cookie(
        version=0,
        name=SESSION_COOKIE_NAME,
        value=signed,
        port=None,
        port_specified=False,
        domain="",
        domain_specified=False,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=False,
        expires=(datetime.now(UTC) + timedelta(seconds=3600)).timestamp(),
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": True, "SameSite": "lax"},
        rfc2109=False,
    )


def _create_admin_client(database: Database) -> tuple[TestClient, int]:
    """Create a test account with ADMIN + BASIC claims and ACTIVE status.

    Returns (client, account_id).
    """
    from ratelimit import limiter
    from app import secret

    limiter.reset()

    with database.session() as s:
        act = create_account(
            "admin_user",
            "admin@test.com",
            ExternalAuthProvider.test,
            "admin_ext_1",
            claims=AccountClaims.BASIC | AccountClaims.ADMIN,
        )
        act.status = AccountStatus.ACTIVE
        s.add(act)
        s.commit()
        act_id = act.id

    client = TestClient(app)
    client.cookies.jar.set_cookie(_mk_auth_cookie(secret, act_id))
    return client, act_id


def _create_pending_account(database: Database, username: str, ext_id: str) -> int:
    """Create a pending-approval account and return its ID."""
    with database.session() as s:
        act = create_account(
            username,
            f"{username}@test.com",
            ExternalAuthProvider.test,
            ext_id,
            claims=AccountClaims.BASIC,
        )
        # Default is PENDING_APPROVAL, but be explicit
        act.status = AccountStatus.PENDING_APPROVAL
        s.add(act)
        s.commit()
        return act.id


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def database() -> Iterator[Database]:
    """Yield a started Database instance."""
    with Database() as db:
        yield db


@pytest_asyncio.fixture(scope="function")
async def admin_client(database: Database) -> AsyncIterator[tuple[TestClient, int]]:
    """Yield an authenticated admin client and the admin account ID."""
    client, act_id = _create_admin_client(database)
    with client:
        yield client, act_id


@pytest_asyncio.fixture(scope="function")
async def unauthenticated_client() -> AsyncIterator[TestClient]:
    """Yield an unauthenticated test client."""
    from ratelimit import limiter

    limiter.reset()
    with TestClient(app) as c:
        yield c


# ══════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════


class TestListAccounts:
    """GET /api/v2/account/admin/accounts."""

    def test_list_accounts_requires_admin(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Unauthenticated user cannot list accounts."""
        r = unauthenticated_client.get("/api/v2/account/admin/accounts")
        assert r.status_code == 401

    def test_list_all_accounts(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can list all accounts."""
        client, _ = admin_client
        _create_pending_account(database, "pending1", "ext_p1")

        r = client.get("/api/v2/account/admin/accounts")
        assert r.status_code == 200
        data = r.json()
        # At least the admin + the pending account
        assert len(data) >= 2
        usernames = [a["username"] for a in data]
        assert "admin_user" in usernames
        assert "pending1" in usernames

    def test_list_accounts_filter_by_status(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can filter accounts by status."""
        client, _ = admin_client
        _create_pending_account(database, "pending2", "ext_p2")

        # Filter for pending_approval
        r = client.get("/api/v2/account/admin/accounts?status_filter=pending_approval")
        assert r.status_code == 200
        data = r.json()
        assert all(a["status"] == "pending_approval" for a in data)
        assert any(a["username"] == "pending2" for a in data)

        # Filter for active
        r = client.get("/api/v2/account/admin/accounts?status_filter=active")
        assert r.status_code == 200
        data = r.json()
        assert all(a["status"] == "active" for a in data)

    def test_list_accounts_invalid_filter(
        self, admin_client: tuple[TestClient, int]
    ) -> None:
        """Invalid status filter returns 400."""
        client, _ = admin_client
        r = client.get("/api/v2/account/admin/accounts?status_filter=invalid")
        assert r.status_code == 400


class TestUpdateAccountStatus:
    """POST /api/v2/account/admin/accounts/{id}/status."""

    def test_approve_pending_account(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can approve a pending account."""
        client, _ = admin_client
        pending_id = _create_pending_account(database, "to_approve", "ext_approve")

        r = client.post(
            f"/api/v2/account/admin/accounts/{pending_id}/status",
            json={"status": "active"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "active"
        assert data["username"] == "to_approve"

    def test_ban_account(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can ban an account."""
        client, _ = admin_client
        pending_id = _create_pending_account(database, "to_ban", "ext_ban")

        r = client.post(
            f"/api/v2/account/admin/accounts/{pending_id}/status",
            json={"status": "banned"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "banned"

    def test_defunct_account(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can mark an account as defunct."""
        client, _ = admin_client
        pending_id = _create_pending_account(database, "to_defunct", "ext_defunct")

        r = client.post(
            f"/api/v2/account/admin/accounts/{pending_id}/status",
            json={"status": "defunct"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "defunct"

    def test_invalid_status_rejected(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Invalid status value is rejected."""
        client, _ = admin_client
        pending_id = _create_pending_account(database, "bad_status", "ext_bad")

        r = client.post(
            f"/api/v2/account/admin/accounts/{pending_id}/status",
            json={"status": "nonexistent"},
        )
        assert r.status_code == 422

    def test_nonexistent_account(self, admin_client: tuple[TestClient, int]) -> None:
        """Updating a nonexistent account returns 404."""
        client, _ = admin_client
        r = client.post(
            "/api/v2/account/admin/accounts/99999/status",
            json={"status": "active"},
        )
        assert r.status_code == 404

    def test_requires_admin(self, unauthenticated_client: TestClient) -> None:
        """Unauthenticated user cannot update account status."""
        r = unauthenticated_client.post(
            "/api/v2/account/admin/accounts/1/status",
            json={"status": "active"},
        )
        assert r.status_code == 401


class TestUpdateAccountRole:
    """POST /api/v2/account/admin/accounts/{id}/role."""

    def test_grant_admin_role(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can grant ADMIN claim to another account."""
        client, _ = admin_client
        pending_id = _create_pending_account(database, "grantee", "ext_grantee")

        r = client.post(
            f"/api/v2/account/admin/accounts/{pending_id}/role",
            json={"grant_admin": True},
        )
        assert r.status_code == 200
        data = r.json()
        # ADMIN claim bit is 2
        assert data["claims"] & 2 != 0

    def test_revoke_admin_role(
        self, admin_client: tuple[TestClient, int], database: Database
    ) -> None:
        """Admin can revoke ADMIN claim from an account."""
        client, admin_id = admin_client

        # Create another admin
        with database.session() as s:
            act = create_account(
                "other_admin",
                "other_admin@test.com",
                ExternalAuthProvider.test,
                "ext_other_admin",
                claims=AccountClaims.BASIC | AccountClaims.ADMIN,
            )
            act.status = AccountStatus.ACTIVE
            s.add(act)
            s.commit()
            other_id = act.id

        r = client.post(
            f"/api/v2/account/admin/accounts/{other_id}/role",
            json={"grant_admin": False},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["claims"] & 2 == 0

    def test_nonexistent_account(self, admin_client: tuple[TestClient, int]) -> None:
        """Role update on nonexistent account returns 404."""
        client, _ = admin_client
        r = client.post(
            "/api/v2/account/admin/accounts/99999/role",
            json={"grant_admin": True},
        )
        assert r.status_code == 404


class TestAccountStatusGatesLogin:
    """Account status checks on the OIDC callback login flow."""

    @staticmethod
    def _mock_callback(
        client: TestClient,
        database: Database,
        ext_id: str,
        account_status: AccountStatus,
    ) -> Any:
        """Create an account with a given status and simulate OIDC callback."""
        from unittest.mock import patch, AsyncMock
        from starlette.responses import RedirectResponse
        from http import HTTPStatus
        from routes.auth import AuthMgrs

        with database.session() as s:
            act = create_account(
                f"user_{ext_id}",
                f"{ext_id}@test.com",
                ExternalAuthProvider.test,
                ext_id,
                claims=AccountClaims.BASIC,
            )
            act.status = account_status
            s.add(act)
            s.commit()

        mock_redirect = RedirectResponse("/account", HTTPStatus.FOUND)
        mock_identity = {
            "id": {"sub": ext_id, "email": f"{ext_id}@test.com", "name": "Test"},
            "at": "at_token",
            "exp": 3600,
            "mode": "login",
        }

        original = AuthMgrs.get("test")
        with patch.object(
            original,
            "authenticate",
            new_callable=AsyncMock,
            return_value=(mock_redirect, mock_identity),
        ):
            client.cookies = {"auth_state": "s", "auth_nonce": "n"}
            return client.get(
                "/api/v2/auth/callback/test",
                params={"code": "c", "state": "s"},
                follow_redirects=False,
            )

    def test_pending_account_redirects_to_login_with_error(
        self, unauthenticated_client: TestClient, database: Database
    ) -> None:
        """A pending account is redirected to /login with error query param."""
        r = self._mock_callback(
            unauthenticated_client,
            database,
            "pending_login",
            AccountStatus.PENDING_APPROVAL,
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert "/login" in location
        assert "pending" in location.lower()

    def test_banned_account_redirects_to_login_with_error(
        self, unauthenticated_client: TestClient, database: Database
    ) -> None:
        """A banned account is redirected to /login with error."""
        r = self._mock_callback(
            unauthenticated_client, database, "banned_login", AccountStatus.BANNED
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert "/login" in location
        assert "banned" in location.lower()

    def test_defunct_account_redirects_to_login_with_error(
        self, unauthenticated_client: TestClient, database: Database
    ) -> None:
        """A defunct account is redirected to /login with error."""
        r = self._mock_callback(
            unauthenticated_client, database, "defunct_login", AccountStatus.DEFUNCT
        )
        assert r.status_code == 302
        location = r.headers["location"]
        assert "/login" in location
        assert "disabled" in location.lower()

    def test_active_account_logs_in_normally(
        self, unauthenticated_client: TestClient, database: Database
    ) -> None:
        """An active account proceeds with normal login redirect."""
        r = self._mock_callback(
            unauthenticated_client, database, "active_login", AccountStatus.ACTIVE
        )
        assert r.status_code == 302
        location = r.headers["location"]
        # Should redirect to the original redirect (not /login?error=...)
        assert "error" not in location


class TestRequireLoginStatusGate:
    """RequireLogin dependency rejects non-active accounts."""

    def test_pending_account_rejected_by_require_login(
        self, database: Database
    ) -> None:
        """A pending account session is rejected by RequireLogin."""
        from ratelimit import limiter
        from app import secret

        limiter.reset()

        with database.session() as s:
            act = create_account(
                "pending_user",
                "pending@test.com",
                ExternalAuthProvider.test,
                "ext_pending_rl",
                claims=AccountClaims.BASIC,
            )
            act.status = AccountStatus.PENDING_APPROVAL
            s.add(act)
            s.commit()
            act_id = act.id

        with TestClient(app) as client:
            client.cookies.jar.set_cookie(_mk_auth_cookie(secret, act_id))
            r = client.get("/api/v2/account/profile")
            assert r.status_code == 403
            assert "pending" in r.json()["detail"].lower()

    def test_banned_account_rejected_by_require_login(self, database: Database) -> None:
        """A banned account session is rejected by RequireLogin."""
        from ratelimit import limiter
        from app import secret

        limiter.reset()

        with database.session() as s:
            act = create_account(
                "banned_user",
                "banned@test.com",
                ExternalAuthProvider.test,
                "ext_banned_rl",
                claims=AccountClaims.BASIC,
            )
            act.status = AccountStatus.BANNED
            s.add(act)
            s.commit()
            act_id = act.id

        with TestClient(app) as client:
            client.cookies.jar.set_cookie(_mk_auth_cookie(secret, act_id))
            r = client.get("/api/v2/account/profile")
            assert r.status_code == 403
            assert "banned" in r.json()["detail"].lower()

    def test_defunct_account_rejected_by_require_login(
        self, database: Database
    ) -> None:
        """A defunct account session is rejected by RequireLogin."""
        from ratelimit import limiter
        from app import secret

        limiter.reset()

        with database.session() as s:
            act = create_account(
                "defunct_user",
                "defunct@test.com",
                ExternalAuthProvider.test,
                "ext_defunct_rl",
                claims=AccountClaims.BASIC,
            )
            act.status = AccountStatus.DEFUNCT
            s.add(act)
            s.commit()
            act_id = act.id

        with TestClient(app) as client:
            client.cookies.jar.set_cookie(_mk_auth_cookie(secret, act_id))
            r = client.get("/api/v2/account/profile")
            assert r.status_code == 403
            assert "disabled" in r.json()["detail"].lower()


class TestCompleteRegistrationPendingStatus:
    """POST /api/v2/auth/complete-registration creates a PENDING account."""

    @staticmethod
    def _set_pending_session(client: TestClient, pending: dict) -> None:
        """Inject a pending_registration session."""
        from json import dumps
        from base64 import b64encode
        from itsdangerous import TimestampSigner
        from datetime import datetime, UTC, timedelta
        from routes import SESSION_COOKIE_NAME
        from routes.auth.authenticate import PENDING_REGISTRATION_KEY
        from app import secret

        payload = {PENDING_REGISTRATION_KEY: pending}
        signer = TimestampSigner(secret_key=str(secret))
        signed = signer.sign(b64encode(dumps(payload).encode("utf-8"))).decode("utf-8")

        cookie = Cookie(
            version=0,
            name=SESSION_COOKIE_NAME,
            value=signed,
            port=None,
            port_specified=False,
            domain="",
            domain_specified=False,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=False,
            expires=(datetime.now(UTC) + timedelta(seconds=3600)).timestamp(),
            discard=True,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": True, "SameSite": "lax"},
            rfc2109=False,
        )
        client.cookies.jar.set_cookie(cookie)

    def test_new_account_is_pending_approval(
        self, unauthenticated_client: TestClient, database: Database
    ) -> None:
        """Newly registered account has PENDING_APPROVAL status."""
        self._set_pending_session(
            unauthenticated_client,
            {
                "provider": "test",
                "sub": "new_pending_sub",
                "name": "New Pending",
                "email": "newpending@test.com",
            },
        )

        r = unauthenticated_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "newpendinguser"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "pending_approval"
        assert data["username"] == "newpendinguser"

        # Verify the account in the DB has PENDING_APPROVAL status
        from sqlalchemy import select
        from models import DBAccount as Account

        with database.session() as s:
            act = s.scalars(
                select(Account).where(Account.username == "newpendinguser")
            ).first()
            assert act is not None
            assert act.status == AccountStatus.PENDING_APPROVAL

    def test_no_session_established_after_registration(
        self, unauthenticated_client: TestClient, database: Database
    ) -> None:
        """After registration, no auth session is established (account is pending)."""
        self._set_pending_session(
            unauthenticated_client,
            {
                "provider": "test",
                "sub": "no_session_sub",
                "name": "No Session",
                "email": "nosession@test.com",
            },
        )

        r = unauthenticated_client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "nosessionuser"},
        )
        assert r.status_code == 201

        # Trying to access a protected endpoint should fail
        r = unauthenticated_client.get("/api/v2/account/profile")
        assert r.status_code == 401


class TestAdminApprovalWorkflow:
    """End-to-end: register → pending → admin approves → can login."""

    @staticmethod
    def _set_pending_session(client: TestClient, pending: dict) -> None:
        """Inject a pending_registration session."""
        TestCompleteRegistrationPendingStatus._set_pending_session(client, pending)

    def test_full_approval_workflow(self, database: Database) -> None:
        """Register → pending → admin approves → account is active."""
        from ratelimit import limiter

        limiter.reset()

        # Step 1: Register a new account (it becomes PENDING)
        with TestClient(app) as reg_client:
            self._set_pending_session(
                reg_client,
                {
                    "provider": "test",
                    "sub": "workflow_sub",
                    "name": "Workflow User",
                    "email": "workflow@test.com",
                },
            )
            r = reg_client.post(
                "/api/v2/auth/complete-registration",
                json={"username": "workflow_user"},
            )
            assert r.status_code == 201
            new_id = r.json()["id"]
            assert r.json()["status"] == "pending_approval"

        # Step 2: Create an admin and approve the account
        admin_client, _ = _create_admin_client(database)
        with admin_client:
            r = admin_client.post(
                f"/api/v2/account/admin/accounts/{new_id}/status",
                json={"status": "active"},
            )
            assert r.status_code == 200
            assert r.json()["status"] == "active"

        # Step 3: Verify the account is now active in the DB
        from sqlalchemy import select
        from models import DBAccount as Account

        with database.session() as s:
            act = s.scalars(select(Account).where(Account.id == new_id)).first()
            assert act is not None
            assert act.status == AccountStatus.ACTIVE
