"""Tests for scheduler catch-up resilience and early event submission (v2 pipeline).

Covers:
- Scheduler idempotency: advance_rotation() pipeline advancement
- Deadline guard: auto_select_happy_hour() skips when deadline hasn't passed
- Early submission: any tyrant can submit for future weeks
- CURRENT tyrant can submit and is marked CHOSEN
- Strike evaluation: evaluate_strikes() at 9AM Friday
- Pre-booked event resolves via auto_select
"""

import logging
from datetime import datetime, UTC, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app import app, secret
from db import Database
from db.functions import (
    create_account,
    create_event,
    create_location,
    create_tyrant_assignment,
    get_current_active_assignment,
)
from models import (
    AccountClaims,
    AccountStatus,
    ExternalAuthProvider,
    TyrantAssignmentStatus,
)
from models.happyhour.location import Location
from ratelimit import limiter
from tests.conftest import _mk_auth_cookie


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


def _make_location(s: Session, name: str = "Catchup Bar") -> Location:
    loc = create_location(
        s,
        Name=name,
        URL="https://catchupbar.com",
        AddressRaw="123 Catchup St",
        Number=123,
        StreetName="Catchup St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    s.commit()
    return loc


def _make_user(
    s: Session,
    name: str,
    claims: AccountClaims = AccountClaims.HAPPY_HOUR | AccountClaims.HAPPY_HOUR_TYRANT,
):
    act = create_account(
        name,
        f"{name}@test.com",
        ExternalAuthProvider.test,
        name,
        claims=claims,
    )
    act.status = AccountStatus.ACTIVE
    s.add(act)
    s.commit()
    return act


class TestAdvanceRotationCatchUp:
    """Verify advance_rotation() is idempotent during catch-up firings."""

    @pytest.mark.asyncio
    async def test_keeps_current_when_unresolved(
        self, db_session: Session, database: Database
    ) -> None:
        """advance_rotation() should keep CURRENT person if they haven't resolved."""
        admin1 = _make_user(db_session, "catchup_a")
        admin2 = _make_user(db_session, "catchup_b")

        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.ON_DECK,
        )
        db_session.commit()

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
        ):
            from scheduler import advance_rotation

            await advance_rotation()

        current = get_current_active_assignment(db_session)
        assert current is not None
        assert current.Account.username == "catchup_a"


class TestAutoSelectDeadlineGuard:
    """Verify auto_select_happy_hour() respects deadline timing."""

    @pytest.mark.asyncio
    async def test_skips_when_deadline_not_passed(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """auto_select should not mark MISSED if the deadline is still in the future."""
        admin = _make_user(db_session, "early_autosel")
        _make_location(db_session, name="Autosel Bar")

        assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=2),
            status=TyrantAssignmentStatus.CURRENT,
        )
        db_session.commit()

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_happy_hour_users"),
        ):
            with caplog.at_level(logging.INFO):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "still has time" in caplog.text

        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.CURRENT


class TestEarlySubmission:
    """Verify any HAPPY_HOUR_TYRANT can submit for a future week without
    affecting the current rotation state."""

    def test_future_week_submit_while_someone_else_current(
        self, db_session: Session
    ) -> None:
        """Bob can submit for a future week while Alice is CURRENT this week."""
        alice = _make_user(db_session, "es_alice")
        bob = _make_user(db_session, "es_bob")

        now = datetime.now(UTC)
        a1 = create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        a2 = create_tyrant_assignment(
            db_session,
            bob.id,
            cycle=1,
            position=1,
            assigned_at=now,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, bob.id))

            loc_r = c.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
            assert loc_r.status_code == 201
            loc_id = loc_r.json()["id"]

            future_time = (datetime.now(UTC) + timedelta(days=10)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": future_time},
            )
            assert r.status_code == 201
            assert r.json()["tyrant_username"] == "es_bob"

        db_session.refresh(a1)
        assert a1.status == TyrantAssignmentStatus.CURRENT

        db_session.refresh(a2)
        assert a2.status == TyrantAssignmentStatus.SCHEDULED

    def test_current_user_can_submit_for_current_week(
        self, db_session: Session
    ) -> None:
        """The CURRENT tyrant can submit and is marked CHOSEN."""
        alice = _make_user(db_session, "cur_alice")

        now = datetime.now(UTC)
        a1 = create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))

            loc_r = c.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
            loc_id = loc_r.json()["id"]

            event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": event_time},
            )
            assert r.status_code == 201

        db_session.refresh(a1)
        assert a1.status == TyrantAssignmentStatus.CHOSEN

    def test_non_tyrant_rejected(self, db_session: Session) -> None:
        """A user without HAPPY_HOUR_TYRANT is rejected."""
        regular = _make_user(
            db_session,
            "es_regular",
            claims=AccountClaims.HAPPY_HOUR | AccountClaims.BASIC,
        )

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, regular.id))

            loc_r = c.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
            loc_id = loc_r.json()["id"]

            event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": event_time},
            )
            assert r.status_code == 403

    def test_duplicate_week_blocked(self, db_session: Session) -> None:
        """Two events in the same week are blocked regardless of who submits."""
        alice = _make_user(db_session, "dup_alice")
        bob = _make_user(db_session, "dup_bob")

        now = datetime.now(UTC)
        create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.CURRENT,
        )
        db_session.commit()

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, alice.id))
            loc_r = c.post("/api/v2/happyhour/locations", json=LOCATION_DATA)
            loc_id = loc_r.json()["id"]
            event_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": event_time},
            )
            assert r.status_code == 201

        limiter.reset()
        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, bob.id))
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": event_time},
            )
            assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_pre_booked_event_resolves_via_scheduler(
        self, db_session: Session, database: Database
    ) -> None:
        """When a tyrant pre-books an event, auto_select sees it and marks CHOSEN."""
        charlie = _make_user(db_session, "ar_charlie")
        loc = _make_location(db_session, name="Autosolve Bar")

        assignment = create_tyrant_assignment(
            db_session,
            charlie.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=3),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.CURRENT,
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(hours=2),
            tyrant_id=charlie.id,
            description="Pre-booked",
        )
        db_session.commit()

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_happy_hour_users"),
        ):
            from scheduler import auto_select_happy_hour

            await auto_select_happy_hour()

        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.CHOSEN


class TestEvaluateStrikes:
    """Verify evaluate_strikes() counts and penalizes consecutive misses."""

    @pytest.mark.asyncio
    async def test_missed_counts_as_strike(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A MISSED assignment at 9AM Friday counts as a strike."""
        admin = _make_user(db_session, "strike_admin")

        create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.MISSED,
        )
        db_session.commit()

        with patch("db.Database", return_value=database):
            with caplog.at_level(logging.WARNING):
                from scheduler import evaluate_strikes

                await evaluate_strikes()

            assert "Strike evaluated" in caplog.text
            assert "1 consecutive" in caplog.text

    @pytest.mark.asyncio
    async def test_no_strike_when_chosen(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A CHOSEN assignment does not get a strike."""
        admin = _make_user(db_session, "nostrike_admin")

        create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        db_session.commit()

        with patch("db.Database", return_value=database):
            from scheduler import evaluate_strikes

            await evaluate_strikes()
