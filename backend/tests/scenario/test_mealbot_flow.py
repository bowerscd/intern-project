"""End-to-end scenario tests for the mealbot flow."""

from typing import TYPE_CHECKING

from starlette.testclient import TestClient

if TYPE_CHECKING:
    from db import Database


class TestAuthenticatedMealbotFlow:
    """v2 authenticated endpoints with auth'd client."""

    def test_create_users_and_track_meals(
        self, authenticated_client: TestClient, database: "Database"
    ) -> None:
        """Verify user creation (via DB), meal recording, and summary via v2.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from db.functions import create_account
        from models import AccountClaims, AccountStatus, ExternalAuthProvider

        c = authenticated_client

        # Create users directly in the database
        for username in ("alice", "bobbi"):
            with database.session() as s:
                act = create_account(
                    username=username,
                    email=None,
                    account_provider=ExternalAuthProvider.test,
                    external_unique_id=username,
                    claims=AccountClaims.MEALBOT,
                )
                act.status = AccountStatus.ACTIVE
                s.add(act)
                s.commit()

        # Record some meals — auth user is "test", must be a participant
        c.post(
            "/api/v2/mealbot/record",
            json={"payer": "test", "recipient": "alice", "credits": 2},
        )
        c.post(
            "/api/v2/mealbot/record",
            json={"payer": "bobbi", "recipient": "test", "credits": 1},
        )

        # Check full ledger
        r = c.get("/api/v2/mealbot/ledger")
        assert r.status_code == 200
        assert len(r.json()["items"]) == 2

        # Check summary
        r = c.get("/api/v2/mealbot/summary", params={"user": "alice"})
        assert r.status_code == 200
