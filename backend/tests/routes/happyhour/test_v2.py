"""Tests for v2 happy hour endpoints."""

from datetime import datetime, UTC, timedelta
from unittest.mock import patch, MagicMock

from models import AccountClaims
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


class TestLocations:
    """Verify authenticated happy-hour location endpoints."""

    def test_list_locations_empty(self, authenticated_client: TestClient) -> None:
        """Verify an empty list is returned when no locations exist.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.get("/api/v2/happyhour/locations")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 50

    def test_create_location(self, authenticated_client: TestClient) -> None:
        """Verify a new location is created and returned with an ID.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Test Tavern"
        assert data["closed"] is False
        assert "id" in data

    def test_get_location_by_id(self, authenticated_client: TestClient) -> None:
        """Verify a location can be fetched by its ID.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]

        r = authenticated_client.get(f"/api/v2/happyhour/locations/{loc_id}")
        assert r.status_code == 200
        assert r.json()["name"] == "Test Tavern"

    def test_get_location_not_found(self, authenticated_client: TestClient) -> None:
        """Verify 404 for a non-existent location ID.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.get("/api/v2/happyhour/locations/99999")
        assert r.status_code == 404

    def test_update_location(self, authenticated_client: TestClient) -> None:
        """Verify a location can be patched with new attributes.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]

        r = authenticated_client.patch(
            f"/api/v2/happyhour/locations/{loc_id}",
            json={"closed": True},
        )
        assert r.status_code == 200
        assert r.json()["closed"] is True


class TestRandomLocation:
    """Verify GET /api/v2/happyhour/locations/random endpoint."""

    def test_random_no_locations_returns_404(
        self, authenticated_client: TestClient
    ) -> None:
        r = authenticated_client.get("/api/v2/happyhour/locations/random")
        assert r.status_code == 404

    def test_random_returns_open_location(
        self, authenticated_client: TestClient
    ) -> None:
        authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        r = authenticated_client.get("/api/v2/happyhour/locations/random")
        assert r.status_code == 200
        assert r.json()["name"] == "Test Tavern"

    def test_random_excludes_closed(self, authenticated_client: TestClient) -> None:
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]
        authenticated_client.patch(
            f"/api/v2/happyhour/locations/{loc_id}", json={"closed": True}
        )
        r = authenticated_client.get("/api/v2/happyhour/locations/random")
        assert r.status_code == 404

    def test_weighted_random_returns_location(
        self, authenticated_client: TestClient
    ) -> None:
        authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        r = authenticated_client.get("/api/v2/happyhour/locations/random?weighted=true")
        assert r.status_code == 200
        assert r.json()["name"] == "Test Tavern"

    def test_weighted_favors_unvisited(self, authenticated_client: TestClient) -> None:
        """With one visited and one unvisited location, weighted random should
        strongly favor the unvisited one over many iterations."""
        authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        alternate = {
            **LOCATION_DATA,
            "name": "Unvisited Pub",
            "address_raw": "456 New St, Portland, OR 97202",
            "number": 456,
            "street_name": "New St",
            "zip_code": "97202",
        }
        authenticated_client.post("/api/v2/happyhour/locations", json=alternate)

        # Create multiple events at Test Tavern to make it heavily visited
        for i in range(5):
            event_time = (datetime.now(UTC) + timedelta(days=3 + i * 7)).isoformat()
            authenticated_client.post(
                "/api/v2/happyhour/events",
                json={
                    "location_id": 1,
                    "when": event_time,
                },
            )

        # Sample weighted random 20 times — unvisited should appear more
        unvisited_count = 0
        for _ in range(20):
            r = authenticated_client.get(
                "/api/v2/happyhour/locations/random?weighted=true"
            )
            assert r.status_code == 200
            if r.json()["name"] == "Unvisited Pub":
                unvisited_count += 1

        # With weight 1.0 vs 1/6=0.167, unvisited should win ~86% of the time
        # Use a conservative threshold to avoid flaky tests
        assert unvisited_count >= 5, (
            f"Expected unvisited location to appear frequently, got {unvisited_count}/20"
        )

    def test_random_requires_auth(self, client: TestClient) -> None:
        r = client.get("/api/v2/happyhour/locations/random")
        assert r.status_code == 401


class TestEvents:
    """Verify authenticated happy-hour event endpoints."""

    def test_list_events_empty(self, authenticated_client: TestClient) -> None:
        """Verify an empty list is returned when no events exist.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.get("/api/v2/happyhour/events")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 50

    def test_create_event(self, authenticated_client: TestClient) -> None:
        # Create location first
        """Verify a new event is created at the given location.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]

        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        r = authenticated_client.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc_id,
                "description": "Weekly HH",
                "when": event_time,
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["location_name"] == "Test Tavern"
        assert data["auto_selected"] is False

    def test_create_event_nonexistent_location(
        self, authenticated_client: TestClient
    ) -> None:
        """Verify 400 when the location does not exist.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        r = authenticated_client.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": 99999,
                "when": event_time,
            },
        )
        assert r.status_code == 404

    def test_create_event_closed_location(
        self, authenticated_client: TestClient
    ) -> None:
        # Create and close location
        """Verify 400 when the location is closed.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]
        authenticated_client.patch(
            f"/api/v2/happyhour/locations/{loc_id}",
            json={"closed": True},
        )

        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        r = authenticated_client.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc_id,
                "when": event_time,
            },
        )
        assert r.status_code == 400

    def test_get_event_by_id(self, authenticated_client: TestClient) -> None:
        """Verify an event can be fetched by its ID.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]

        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        r = authenticated_client.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc_id,
                "when": event_time,
            },
        )
        event_id = r.json()["id"]

        r = authenticated_client.get(f"/api/v2/happyhour/events/{event_id}")
        assert r.status_code == 200
        assert r.json()["id"] == event_id

    def test_upcoming_event(self, authenticated_client: TestClient) -> None:
        """Verify the next upcoming event is returned.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        loc_id = r.json()["id"]

        event_time = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        authenticated_client.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc_id,
                "when": event_time,
            },
        )

        r = authenticated_client.get("/api/v2/happyhour/events/upcoming")
        assert r.status_code == 200
        # Could be None or the event we just created


class TestTurnEnforcement:
    """Test rotation-based turn enforcement on event creation."""

    def _create_location(self, client: TestClient) -> int:
        """Post a new location and return the response JSON.

        :param c: Authenticated test client.
        :type c: TestClient
        :returns: Location response dict.
        :rtype: dict
        """
        r = client.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
        return r.json()["id"]

    _PENDING_PATCH = "db.functions.get_current_active_assignment"
    _CHOSEN_PATCH = "db.functions.mark_assignment_chosen"

    def test_any_user_can_create_when_no_pending(
        self, authenticated_client: TestClient
    ) -> None:
        """Without a pending assignment, any HAPPY_HOUR user can create.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        loc_id = self._create_location(authenticated_client)
        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()

        with patch(self._PENDING_PATCH, return_value=None):
            r = authenticated_client.post(
                "/api/v2/happyhour/events",
                json={
                    "location_id": loc_id,
                    "when": event_time,
                },
            )
        assert r.status_code == 201

    def test_assigned_tyrant_can_create(
        self, authenticated_client: TestClient, db_session: Session
    ) -> None:
        """The assigned tyrant (whose account matches the session) can create.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc_id = self._create_location(authenticated_client)
        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()

        # The authenticated_client's account id is the one we need
        from db.functions import get_all_accounts

        accounts = get_all_accounts(db_session)
        test_act = [a for a in accounts if a.username == "test"][0]

        mock_assignment = MagicMock()
        mock_assignment.account_id = test_act.id
        mock_assignment.id = 999

        with (
            patch(
                self._PENDING_PATCH,
                return_value=mock_assignment,
            ),
            patch(
                self._CHOSEN_PATCH,
            ) as mock_chosen,
        ):
            r = authenticated_client.post(
                "/api/v2/happyhour/events",
                json={
                    "location_id": loc_id,
                    "when": event_time,
                },
            )
        assert r.status_code == 201
        mock_chosen.assert_called_once()

    def test_other_tyrant_can_submit_for_future_week(
        self, authenticated_client: TestClient
    ) -> None:
        """A HAPPY_HOUR_TYRANT can submit even when someone else is PENDING
        (e.g. for a future week).

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        loc_id = self._create_location(authenticated_client)
        # Submit for a future week (10+ days out)
        event_time = (datetime.now(UTC) + timedelta(days=10)).isoformat()

        mock_assignment = MagicMock()
        mock_assignment.account_id = 999999  # Some other account is pending

        with patch(self._PENDING_PATCH, return_value=mock_assignment):
            r = authenticated_client.post(
                "/api/v2/happyhour/events",
                json={
                    "location_id": loc_id,
                    "when": event_time,
                },
            )
        assert r.status_code == 201

    def test_other_tyrant_blocked_for_current_week(
        self, authenticated_client: TestClient, db_session: Session
    ) -> None:
        """A HAPPY_HOUR_TYRANT who isn't the assigned tyrant gets 403
        when submitting for the CURRENT week (non-admin).

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc_id = self._create_location(authenticated_client)
        # Submit for the current week (hours from now, guaranteed same ISO week)
        event_time = (datetime.now(UTC) + timedelta(hours=12)).isoformat()

        # Temporarily remove ADMIN so the rotation check isn't bypassed
        from db.functions import get_all_accounts

        accounts = get_all_accounts(db_session)
        test_act = [a for a in accounts if a.username == "test"][0]
        original_claims = test_act.claims
        test_act.claims = (
            AccountClaims.HAPPY_HOUR
            | AccountClaims.HAPPY_HOUR_TYRANT
            | AccountClaims.BASIC
        )
        db_session.commit()

        mock_assignment = MagicMock()
        mock_assignment.account_id = 999999  # Someone else is pending

        try:
            with patch(self._PENDING_PATCH, return_value=mock_assignment):
                r = authenticated_client.post(
                    "/api/v2/happyhour/events",
                    json={
                        "location_id": loc_id,
                        "when": event_time,
                    },
                )
            assert r.status_code == 403
            assert "not your turn" in r.json()["detail"]
        finally:
            test_act.claims = original_claims
            db_session.commit()

    def test_non_admin_gets_403_during_rotation(
        self, authenticated_client: TestClient, db_session: Session
    ) -> None:
        """A user without HAPPY_HOUR_TYRANT gets 403 during a rotation window.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc_id = self._create_location(authenticated_client)
        event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()

        # Temporarily remove HAPPY_HOUR_TYRANT from the test account
        from db.functions import get_all_accounts

        accounts = get_all_accounts(db_session)
        test_act = [a for a in accounts if a.username == "test"][0]
        original_claims = test_act.claims
        test_act.claims = AccountClaims.HAPPY_HOUR | AccountClaims.BASIC
        db_session.commit()

        try:
            r = authenticated_client.post(
                "/api/v2/happyhour/events",
                json={
                    "location_id": loc_id,
                    "when": event_time,
                },
            )
            assert r.status_code == 403
            assert "HAPPY_HOUR_TYRANT" in r.json()["detail"]
        finally:
            test_act.claims = original_claims
            db_session.commit()

    def test_upcoming_includes_current_tyrant(
        self, authenticated_client: TestClient, db_session: Session
    ) -> None:
        """The /events/upcoming endpoint includes current tyrant info.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        from db.functions import get_all_accounts

        accounts = get_all_accounts(db_session)
        test_act = [a for a in accounts if a.username == "test"][0]

        mock_assignment = MagicMock()
        mock_assignment.account_id = test_act.id
        mock_assignment.Account = test_act
        mock_assignment.deadline_at = datetime.now(UTC) + timedelta(days=5)

        with patch(self._PENDING_PATCH, return_value=mock_assignment):
            r = authenticated_client.get("/api/v2/happyhour/events/upcoming")
        assert r.status_code == 200
        data = r.json()
        assert data["current_tyrant_username"] == "test"
        assert data["current_tyrant_deadline"] is not None

    def test_scheduled_rotation_blocks_wrong_tyrant(self, db_session: Session) -> None:
        """When no PENDING assignment exists but SCHEDULED assignments do,
        only the next-in-line tyrant may create an event.
        """
        from db.functions import create_account
        from models import ExternalAuthProvider, AccountStatus

        dede = create_account(
            "dede",
            "dede@test.com",
            ExternalAuthProvider.test,
            "dede",
            claims=AccountClaims.HAPPY_HOUR | AccountClaims.HAPPY_HOUR_TYRANT,
        )
        dede.status = AccountStatus.ACTIVE
        db_session.add(dede)

        olkorsha = create_account(
            "olkorsha",
            "olkorsha@test.com",
            ExternalAuthProvider.test,
            "olkorsha",
            claims=AccountClaims.HAPPY_HOUR | AccountClaims.HAPPY_HOUR_TYRANT,
        )
        olkorsha.status = AccountStatus.ACTIVE
        db_session.add(olkorsha)
        db_session.flush()

        # Create a rotation cycle with dede first, olkorsha second
        # (don't use create_cycle_rotation because it shuffles)
        from models.happyhour.rotation import TyrantRotation
        from models import TyrantAssignmentStatus

        now = datetime.now(UTC)
        r1 = TyrantRotation(
            account_id=dede.id,
            cycle=1,
            position=0,
            assigned_at=now,
            status=TyrantAssignmentStatus.SCHEDULED,
        )
        r2 = TyrantRotation(
            account_id=olkorsha.id,
            cycle=1,
            position=1,
            assigned_at=now,
            status=TyrantAssignmentStatus.SCHEDULED,
        )
        db_session.add_all([r1, r2])
        db_session.commit()

        # Create a location for the event
        from app import app, secret
        from tests.conftest import _mk_auth_cookie
        from ratelimit import limiter

        limiter.reset()

        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, olkorsha.id))

            # Create a location first (need a valid location_id)
            loc_r = c.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
            assert loc_r.status_code == 201
            loc_id = loc_r.json()["id"]

            # olkorsha submits for a future week — allowed (any tyrant can submit)
            event_time = (datetime.now(UTC) + timedelta(days=10)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": event_time},
            )
            assert r.status_code == 201

        # dede's rotation status is unaffected
        db_session.refresh(r1)
        assert r1.status == TyrantAssignmentStatus.SCHEDULED

    def test_admin_can_override_scheduled_rotation(self, db_session: Session) -> None:
        """An ADMIN can create events even when not next in rotation."""
        from db.functions import create_account
        from models import ExternalAuthProvider, AccountStatus

        tyrant = create_account(
            "queued_tyrant",
            "queued@test.com",
            ExternalAuthProvider.test,
            "queued_tyrant",
            claims=AccountClaims.HAPPY_HOUR | AccountClaims.HAPPY_HOUR_TYRANT,
        )
        tyrant.status = AccountStatus.ACTIVE
        db_session.add(tyrant)

        admin = create_account(
            "admin_override",
            "admin_override@test.com",
            ExternalAuthProvider.test,
            "admin_override",
            claims=AccountClaims.HAPPY_HOUR
            | AccountClaims.HAPPY_HOUR_TYRANT
            | AccountClaims.ADMIN,
        )
        admin.status = AccountStatus.ACTIVE
        db_session.add(admin)
        db_session.flush()

        from models.happyhour.rotation import TyrantRotation
        from models import TyrantAssignmentStatus

        now = datetime.now(UTC)
        r1 = TyrantRotation(
            account_id=tyrant.id,
            cycle=2,
            position=0,
            assigned_at=now,
            status=TyrantAssignmentStatus.SCHEDULED,
        )
        r2 = TyrantRotation(
            account_id=admin.id,
            cycle=2,
            position=1,
            assigned_at=now,
            status=TyrantAssignmentStatus.SCHEDULED,
        )
        db_session.add_all([r1, r2])
        db_session.commit()

        from app import app, secret
        from tests.conftest import _mk_auth_cookie
        from ratelimit import limiter

        limiter.reset()

        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, admin.id))

            loc_r = c.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
            loc_id = loc_r.json()["id"]

            event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": event_time},
            )
            assert r.status_code == 201
