"""Tests for mealbot disaster recovery — void (delete) meal records."""

from starlette.testclient import TestClient

from db import Database
from db.functions import create_account
from models import AccountClaims, AccountStatus, ExternalAuthProvider


def _add_user(database: Database, username: str) -> None:
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


class TestVoidRecord:
    """Test DELETE /api/v2/mealbot/record/{id}."""

    def test_void_requires_auth(self, client: TestClient) -> None:
        r = client.delete("/api/v2/mealbot/record/1")
        assert r.status_code == 401

    def test_void_nonexistent_record(self, authenticated_client: TestClient) -> None:
        r = authenticated_client.delete("/api/v2/mealbot/record/99999")
        assert r.status_code == 404

    def test_void_own_record_as_payer(
        self, authenticated_client: TestClient, database: Database
    ) -> None:
        _add_user(database, "alice")
        # Create a record
        r = authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "test", "recipient": "alice", "credits": 3},
        )
        assert r.status_code == 200
        # Get the record ID from the ledger
        ledger = authenticated_client.get("/api/v2/mealbot/ledger")
        record_id = ledger.json()["items"][0]["id"]
        # Void it
        r = authenticated_client.delete(f"/api/v2/mealbot/record/{record_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "voided"

    def test_void_own_record_as_recipient(
        self, authenticated_client: TestClient, database: Database
    ) -> None:
        _add_user(database, "alice")
        # Create a record where test is the recipient
        r = authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "alice", "recipient": "test", "credits": 2},
        )
        assert r.status_code == 200
        # Get the record ID from the ledger
        ledger = authenticated_client.get("/api/v2/mealbot/ledger")
        record_id = ledger.json()["items"][0]["id"]
        # Void it (test is the recipient)
        r = authenticated_client.delete(f"/api/v2/mealbot/record/{record_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "voided"

    def test_void_updates_ledger(
        self, authenticated_client: TestClient, database: Database
    ) -> None:
        _add_user(database, "alice")
        # Create a record
        authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "test", "recipient": "alice", "credits": 5},
        )
        # Check ledger has 1 record
        ledger = authenticated_client.get("/api/v2/mealbot/ledger")
        assert ledger.json()["total"] == 1
        record_id = ledger.json()["items"][0]["id"]
        # Void it
        authenticated_client.delete(f"/api/v2/mealbot/record/{record_id}")
        # Check ledger is now empty
        ledger = authenticated_client.get("/api/v2/mealbot/ledger")
        assert ledger.json()["total"] == 0

    def test_record_response_includes_id(
        self, authenticated_client: TestClient, database: Database
    ) -> None:
        _add_user(database, "alice")
        authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "test", "recipient": "alice", "credits": 1},
        )
        ledger = authenticated_client.get("/api/v2/mealbot/ledger")
        record = ledger.json()["items"][0]
        assert "id" in record
        assert isinstance(record["id"], int)

    def test_void_not_involved_forbidden(
        self, mealbot_only_client: TestClient, database: Database
    ) -> None:
        """Users not involved in a record (and not ADMIN) cannot void it."""
        _add_user(database, "alice")
        _add_user(database, "bobbi")

        # Create a record between alice and bobbi directly in the DB
        from db.functions import create_receipt

        with database.session() as s:
            create_receipt(s, "alice", "bobbi", 1)
            s.commit()

        # Get the record ID — mealbot_only_client is "mealbot_user", not involved
        ledger = mealbot_only_client.get("/api/v2/mealbot/ledger")
        uninvolved_records = [
            r
            for r in ledger.json()["items"]
            if r["payer"] != "mealbot_user" and r["recipient"] != "mealbot_user"
        ]
        if uninvolved_records:
            record_id = uninvolved_records[0]["id"]
            r = mealbot_only_client.delete(f"/api/v2/mealbot/record/{record_id}")
            assert r.status_code == 403
            assert "involved" in r.json()["detail"].lower()


class TestVoidRecordByAdmin:
    """Test that ADMIN users can void any mealbot record."""

    def test_admin_can_void_any_record(
        self, admin_mealbot_client: TestClient, database: Database
    ) -> None:
        """An admin can void a record they're not involved in."""
        _add_user(database, "alice")
        _add_user(database, "bobbi")

        # Create a record between alice and bobbi directly in the DB
        from db.functions import create_receipt

        with database.session() as s:
            create_receipt(s, "alice", "bobbi", 2)
            s.commit()

        # admin_mealbot_client is "admin_mb_user" — not involved at all
        ledger = admin_mealbot_client.get("/api/v2/mealbot/ledger")
        records = [
            r
            for r in ledger.json()["items"]
            if r["payer"] == "alice" and r["recipient"] == "bobbi"
        ]
        assert len(records) >= 1
        record_id = records[0]["id"]

        r = admin_mealbot_client.delete(f"/api/v2/mealbot/record/{record_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "voided"
