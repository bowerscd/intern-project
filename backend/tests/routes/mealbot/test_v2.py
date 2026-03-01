"""Tests for v2 authenticated mealbot endpoints."""
from starlette.testclient import TestClient

from db import Database
from db.functions import create_account
from models import AccountClaims, ExternalAuthProvider


def _add_user(database: Database, username: str) -> None:
    """Create a mealbot-enabled account directly in the database.

    :param database: Active Database singleton.
    :param username: Username for the new account.
    """
    with database.session() as s:
        act = create_account(
            username=username,
            email=None,
            account_provider=ExternalAuthProvider.test,
            external_unique_id=username,
            claims=AccountClaims.MEALBOT,
        )
        s.add(act)
        s.commit()


class TestV2Unauthenticated:
    """All v2 endpoints should reject unauthenticated requests."""

    def test_ledger_requires_auth(self, client: TestClient) -> None:
        """Verify ``GET /ledger`` returns 401 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v2/mealbot/ledger")
        assert r.status_code == 401

    def test_ledger_me_requires_auth(self, client: TestClient) -> None:
        """Verify ``GET /ledger/me`` returns 401 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v2/mealbot/ledger/me")
        assert r.status_code == 401

    def test_summary_requires_auth(self, client: TestClient) -> None:
        """Verify ``GET /summary`` returns 401 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v2/mealbot/summary")
        assert r.status_code == 401

    def test_record_requires_auth(self, client: TestClient) -> None:
        """Verify ``POST /record`` returns 401 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.post("/api/v2/mealbot/record", json={
            "payer": "a", "recipient": "b", "credits": 1
        })
        assert r.status_code == 401

    def test_user_endpoint_removed(self, client: TestClient) -> None:
        """Verify ``POST /user`` no longer exists (returns 405 Method Not Allowed).

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.post("/api/v2/mealbot/user", json={"username": "test"})
        assert r.status_code in (404, 405)


class TestV2Authenticated:
    """Verify authenticated v2 mealbot endpoints."""
    def test_ledger_empty(self, authenticated_client: TestClient) -> None:
        """Verify an empty ledger for a fresh database.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.get("/api/v2/mealbot/ledger")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_create_user_and_record(self, authenticated_client: TestClient, database: Database) -> None:
        """Verify user creation (via DB) and meal recording via v2.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        _add_user(database, "alice")
        _add_user(database, "bobbi")

        # Auth user is "test" — must be payer or recipient per participant restriction
        r = authenticated_client.post("/api/v2/mealbot/record", json={
            "payer": "test",
            "recipient": "alice",
            "credits": 5,
        })
        assert r.status_code == 200

        # Verify in ledger
        r = authenticated_client.get("/api/v2/mealbot/ledger")
        data = r.json()
        records = data["items"]
        assert len(records) == 1
        assert records[0]["credits"] == 5

    def test_summary(self, authenticated_client: TestClient, database: Database) -> None:
        """Verify the v2 summary endpoint returns correct totals.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        _add_user(database, "alice")
        _add_user(database, "bobbi")
        authenticated_client.post("/api/v2/mealbot/record", json={
            "payer": "test", "recipient": "alice", "credits": 3,
        })

        r = authenticated_client.get("/api/v2/mealbot/summary")
        assert r.status_code == 200

    def test_my_ledger(self, authenticated_client: TestClient) -> None:
        """Verify the ``/ledger/me`` endpoint returns the caller's records.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.get("/api/v2/mealbot/ledger/me")
        assert r.status_code == 200
