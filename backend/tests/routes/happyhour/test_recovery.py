"""Tests for happy hour disaster recovery endpoints — event update, cancel, rotation skip."""

from datetime import datetime, UTC, timedelta
from unittest.mock import patch

from sqlalchemy.orm import Session
from starlette.testclient import TestClient


LOCATION_DATA = {
    "name": "Test Tavern",
    "url": "https://testtavern.com",
    "address_raw": "123 Test St, Portland, OR 97201",
    "number": 123,
    "street_name": "Test St",
    "city": "Portland",
    "state": "OR",
    "zip_code": "97201",
    "latitude": 45.5231,
    "longitude": -122.6765,
}

ALTERNATE_LOCATION_DATA = {
    "name": "Other Pub",
    "url": "https://otherpub.com",
    "address_raw": "456 Other St, Portland, OR 97202",
    "number": 456,
    "street_name": "Other St",
    "city": "Portland",
    "state": "OR",
    "zip_code": "97202",
    "latitude": 45.5250,
    "longitude": -122.6800,
}


def _create_location(client: TestClient, data: dict = LOCATION_DATA) -> int:
    r = client.post("/api/v2/happyhour/locations", json=data)
    assert r.status_code == 201
    return r.json()["id"]


def _create_event(client: TestClient, location_id: int) -> dict:
    event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    r = client.post(
        "/api/v2/happyhour/events",
        json={
            "location_id": location_id,
            "description": "Weekly HH",
            "when": event_time,
        },
    )
    assert r.status_code == 201
    return r.json()


class TestEventUpdate:
    """Test PATCH /api/v2/happyhour/events/{id} for disaster recovery."""

    def test_update_event_description(self, authenticated_client: TestClient) -> None:
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        r = authenticated_client.patch(
            f"/api/v2/happyhour/events/{event['id']}",
            json={"description": "UPDATED: New venue info"},
        )
        assert r.status_code == 200
        assert r.json()["description"] == "UPDATED: New venue info"

    def test_update_event_location(self, authenticated_client: TestClient) -> None:
        loc1_id = _create_location(authenticated_client)
        loc2_id = _create_location(authenticated_client, ALTERNATE_LOCATION_DATA)
        event = _create_event(authenticated_client, loc1_id)
        r = authenticated_client.patch(
            f"/api/v2/happyhour/events/{event['id']}",
            json={"location_id": loc2_id},
        )
        assert r.status_code == 200
        assert r.json()["location_name"] == "Other Pub"

    def test_update_event_closed_location_rejected(
        self, authenticated_client: TestClient
    ) -> None:
        loc1_id = _create_location(authenticated_client)
        loc2_id = _create_location(authenticated_client, ALTERNATE_LOCATION_DATA)
        event = _create_event(authenticated_client, loc1_id)
        # Close the alternate location
        authenticated_client.patch(
            f"/api/v2/happyhour/locations/{loc2_id}", json={"closed": True}
        )
        r = authenticated_client.patch(
            f"/api/v2/happyhour/events/{event['id']}",
            json={"location_id": loc2_id},
        )
        assert r.status_code == 400
        assert "closed" in r.json()["detail"].lower()

    def test_update_nonexistent_event(self, authenticated_client: TestClient) -> None:
        r = authenticated_client.patch(
            "/api/v2/happyhour/events/99999",
            json={"description": "something"},
        )
        assert r.status_code == 404

    def test_update_event_nonexistent_location(
        self, authenticated_client: TestClient
    ) -> None:
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        r = authenticated_client.patch(
            f"/api/v2/happyhour/events/{event['id']}",
            json={"location_id": 99999},
        )
        assert r.status_code == 404

    def test_update_requires_auth(self, client: TestClient) -> None:
        r = client.patch(
            "/api/v2/happyhour/events/1",
            json={"description": "test"},
        )
        assert r.status_code == 401

    def test_update_requires_tyrant_or_admin_claim(
        self, happyhour_only_client: TestClient
    ) -> None:
        r = happyhour_only_client.patch(
            "/api/v2/happyhour/events/1",
            json={"description": "test"},
        )
        assert r.status_code == 403


class TestEventUpdateByAdmin:
    """Test that ADMIN users can update events without HAPPY_HOUR_TYRANT."""

    def test_admin_can_update_event(
        self,
        authenticated_client: TestClient,
        admin_happyhour_client: TestClient,
    ) -> None:
        # Create event with the fully-privileged client
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        # Update it with the admin (no TYRANT claim)
        r = admin_happyhour_client.patch(
            f"/api/v2/happyhour/events/{event['id']}",
            json={"description": "Admin override"},
        )
        assert r.status_code == 200
        assert r.json()["description"] == "Admin override"


class TestEventCancel:
    """Test DELETE /api/v2/happyhour/events/{id} for disaster recovery."""

    def test_cancel_event(self, authenticated_client: TestClient) -> None:
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        r = authenticated_client.delete(f"/api/v2/happyhour/events/{event['id']}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        assert r.json()["event_id"] == event["id"]

    def test_cancel_frees_weekly_slot(self, authenticated_client: TestClient) -> None:
        """After cancelling an event, a new event can be created for the same week."""
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        # Cancel it
        r = authenticated_client.delete(f"/api/v2/happyhour/events/{event['id']}")
        assert r.status_code == 200
        # Create a new event for the same week — should succeed now
        loc2_id = _create_location(authenticated_client, ALTERNATE_LOCATION_DATA)
        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        r = authenticated_client.post(
            "/api/v2/happyhour/events",
            json={"location_id": loc2_id, "when": event_time},
        )
        assert r.status_code == 201
        assert r.json()["location_name"] == "Other Pub"

    def test_cancel_nonexistent_event(self, authenticated_client: TestClient) -> None:
        r = authenticated_client.delete("/api/v2/happyhour/events/99999")
        assert r.status_code == 404

    def test_cancel_requires_auth(self, client: TestClient) -> None:
        r = client.delete("/api/v2/happyhour/events/1")
        assert r.status_code == 401

    def test_cancel_requires_tyrant_or_admin_claim(
        self, happyhour_only_client: TestClient
    ) -> None:
        r = happyhour_only_client.delete("/api/v2/happyhour/events/1")
        assert r.status_code == 403


class TestEventCancelByAdmin:
    """Test that ADMIN users can cancel events without HAPPY_HOUR_TYRANT."""

    def test_admin_can_cancel_event(
        self,
        authenticated_client: TestClient,
        admin_happyhour_client: TestClient,
    ) -> None:
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        r = admin_happyhour_client.delete(f"/api/v2/happyhour/events/{event['id']}")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_cancelled_event_no_longer_retrievable(
        self, authenticated_client: TestClient
    ) -> None:
        loc_id = _create_location(authenticated_client)
        event = _create_event(authenticated_client, loc_id)
        event_id = event["id"]
        authenticated_client.delete(f"/api/v2/happyhour/events/{event_id}")
        r = authenticated_client.get(f"/api/v2/happyhour/events/{event_id}")
        assert r.status_code == 404


class TestRotationSkip:
    """Test POST /api/v2/happyhour/rotation/skip for disaster recovery."""

    _PENDING_PATCH = "db.functions.get_current_pending_assignment"

    def test_skip_requires_auth(self, client: TestClient) -> None:
        r = client.post("/api/v2/happyhour/rotation/skip")
        assert r.status_code == 401

    def test_skip_requires_tyrant_or_admin_claim(
        self, happyhour_only_client: TestClient
    ) -> None:
        r = happyhour_only_client.post("/api/v2/happyhour/rotation/skip")
        assert r.status_code == 403

    def test_skip_no_pending_assignment(self, authenticated_client: TestClient) -> None:
        with patch(self._PENDING_PATCH, return_value=None):
            r = authenticated_client.post("/api/v2/happyhour/rotation/skip")
        assert r.status_code == 404
        assert "No pending" in r.json()["detail"]

    def test_skip_own_turn(
        self, authenticated_client: TestClient, db_session: Session
    ) -> None:
        from db.functions import (
            get_all_accounts,
            create_tyrant_assignment,
        )
        from models.enums import TyrantAssignmentStatus

        accounts = get_all_accounts(db_session)
        test_act = [a for a in accounts if a.username == "test"][0]

        # Create a real pending assignment in the database
        assignment = create_tyrant_assignment(
            db_session,
            account_id=test_act.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        r = authenticated_client.post("/api/v2/happyhour/rotation/skip")
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"
        assert r.json()["skipped_user"] == "test"

        # Verify the assignment was marked as SKIPPED
        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.SKIPPED


class TestRotationSkipByAdmin:
    """Test that ADMIN users can skip anyone's rotation turn."""

    def test_admin_can_skip_others_turn(
        self,
        admin_happyhour_client: TestClient,
        db_session: Session,
    ) -> None:
        """An admin can skip a different user's pending rotation turn."""
        from db.functions import create_tyrant_assignment, get_all_accounts
        from models.enums import TyrantAssignmentStatus

        accounts = get_all_accounts(db_session)
        # The admin_happyhour_client user is "admin_hh_user".
        # Create a pending assignment for a DIFFERENT user.
        other_act = [a for a in accounts if a.username != "admin_hh_user"][0]

        assignment = create_tyrant_assignment(
            db_session,
            account_id=other_act.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        r = admin_happyhour_client.post("/api/v2/happyhour/rotation/skip")
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"

        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.SKIPPED
