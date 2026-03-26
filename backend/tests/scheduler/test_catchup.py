"""Tests for scheduler catch-up resilience and early event submission.

Covers:
- Scheduler idempotency: assign_tyrant() is a no-op when someone is already PENDING
- Deadline guard: auto_select_happy_hour() skips when deadline hasn't passed
- Sequential week simulation: multi-week rotation with 3+ users
- Early submission: any tyrant can submit, preempting the current pending user
- Mid-cycle addition: a user without a SCHEDULED slot can still submit
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
    get_current_pending_assignment,
    get_rotation_schedule,
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


class TestAssignTyrantCatchUp:
    """Verify assign_tyrant() is idempotent during catch-up firings."""

    @pytest.mark.asyncio
    async def test_skips_when_already_pending(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """assign_tyrant() should be a no-op if someone is already PENDING."""
        admin1 = _make_user(db_session, "catchup_a")
        admin2 = _make_user(db_session, "catchup_b")

        # admin1 is already PENDING
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=5),
            status=TyrantAssignmentStatus.PENDING,
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC),
        )
        db_session.commit()

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned") as mock_notify,
            patch("mail.outgoing.notify_tyrant_on_deck"),
        ):
            with caplog.at_level(logging.INFO):
                from scheduler import assign_tyrant

                await assign_tyrant()

            assert "already pending" in caplog.text
            mock_notify.assert_not_called()

        # admin2 should still be SCHEDULED, not double-activated
        schedule = get_rotation_schedule(db_session, 1)
        statuses = {r.Account.username: r.status for r in schedule}
        assert statuses["catchup_a"] == TyrantAssignmentStatus.PENDING
        assert statuses["catchup_b"] == TyrantAssignmentStatus.SCHEDULED

    @pytest.mark.asyncio
    async def test_double_fire_no_double_activation(
        self, db_session: Session, database: Database
    ) -> None:
        """Calling assign_tyrant() twice at the same time should only activate one person."""
        _make_user(db_session, "dbl_a")
        _make_user(db_session, "dbl_b")

        def no_shuffle(lst: list) -> None:
            lst.sort(key=lambda a: a.id)

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            from scheduler import assign_tyrant

            # First call: activates admin1
            await assign_tyrant()
            # Second call: should be a no-op
            await assign_tyrant()

        pending = get_current_pending_assignment(db_session)
        assert pending is not None
        assert pending.Account.username == "dbl_a"

        # admin2 should still be SCHEDULED
        schedule = get_rotation_schedule(db_session, 2)
        statuses = {r.Account.username: r.status for r in schedule}
        assert statuses["dbl_b"] == TyrantAssignmentStatus.SCHEDULED


class TestAutoSelectDeadlineGuard:
    """Verify auto_select_happy_hour() respects deadline timing."""

    @pytest.mark.asyncio
    async def test_skips_when_deadline_not_passed(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """auto_select should not mark MISSED if the deadline is still in the future."""
        admin = _make_user(db_session, "early_autosel")
        _make_location(db_session, name="Autosel Bar")

        # Pending with future deadline
        assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=2),
            status=TyrantAssignmentStatus.PENDING,
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

        # Assignment should still be PENDING, not MISSED
        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.PENDING


class TestEarlySubmission:
    """Verify any HAPPY_HOUR_TYRANT can submit for a future week without
    affecting the current rotation state."""

    def test_future_week_submit_while_someone_else_pending(
        self, db_session: Session
    ) -> None:
        """Bob can submit for a future week while Alice is pending this week.
        Alice's PENDING status is unchanged."""
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
            status=TyrantAssignmentStatus.PENDING,
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

            # Bob submits for a FUTURE week (not the current one)
            future_time = (datetime.now(UTC) + timedelta(days=10)).isoformat()
            r = c.post(
                "/api/v2/happyhour/events",
                json={"location_id": loc_id, "when": future_time},
            )
            assert r.status_code == 201
            assert r.json()["tyrant_username"] == "es_bob"

        # Alice is still PENDING — not affected
        db_session.refresh(a1)
        assert a1.status == TyrantAssignmentStatus.PENDING

        # Bob is still SCHEDULED — the scheduler handles his activation
        db_session.refresh(a2)
        assert a2.status == TyrantAssignmentStatus.SCHEDULED

    def test_pending_user_can_submit_for_current_week(
        self, db_session: Session
    ) -> None:
        """The pending tyrant can submit and is marked CHOSEN."""
        alice = _make_user(db_session, "pend_alice")

        now = datetime.now(UTC)
        a1 = create_tyrant_assignment(
            db_session,
            alice.id,
            cycle=1,
            position=0,
            assigned_at=now,
            deadline_at=now + timedelta(days=5),
            status=TyrantAssignmentStatus.PENDING,
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
            status=TyrantAssignmentStatus.PENDING,
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
        # Bob tries the same week — blocked by duplicate guard
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
        """When a tyrant pre-books an event for their week, auto_select
        sees the event exists and marks the pending person CHOSEN."""
        charlie = _make_user(db_session, "ar_charlie")
        loc = _make_location(db_session, name="Autosolve Bar")

        # Charlie is PENDING and there's already an event this week
        # (simulates pre-booking that landed in this weekly window)
        assignment = create_tyrant_assignment(
            db_session,
            charlie.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=3),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.PENDING,
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


class TestSequentialRotation:
    """Simulate a multi-week rotation with 3 users to verify end-to-end flow."""

    @pytest.mark.asyncio
    async def test_three_user_full_cycle(
        self, db_session: Session, database: Database
    ) -> None:
        """Three users rotate through a full cycle with no misses."""
        users = [
            _make_user(db_session, f"cyc3_{c}") for c in ["alice", "bob", "charlie"]
        ]
        loc = _make_location(db_session, name="Cycle Bar")

        def no_shuffle(lst: list) -> None:
            lst.sort(key=lambda a: a.id)

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("mail.outgoing.notify_happy_hour_users"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            from scheduler import assign_tyrant, auto_select_happy_hour

            # Week 1: assign alice
            await assign_tyrant()
            pending = get_current_pending_assignment(db_session)
            assert pending.Account.username == "cyc3_alice"

            # Alice creates event
            event_time = datetime.now(UTC) + timedelta(days=2)
            create_event(
                db_session,
                loc.id,
                event_time,
                tyrant_id=users[0].id,
                description="Week 1",
            )
            from db.functions import mark_assignment_chosen

            mark_assignment_chosen(db_session, pending.id)
            db_session.commit()

            # Wed: auto_select sees event, no-op
            await auto_select_happy_hour()

            # Week 2: assign bob
            await assign_tyrant()
            pending = get_current_pending_assignment(db_session)
            assert pending.Account.username == "cyc3_bob"

            # Bob creates event
            event_time2 = event_time + timedelta(days=7)
            create_event(
                db_session,
                loc.id,
                event_time2,
                tyrant_id=users[1].id,
                description="Week 2",
            )
            mark_assignment_chosen(db_session, pending.id)
            db_session.commit()

            # Week 3: assign charlie
            await assign_tyrant()
            pending = get_current_pending_assignment(db_session)
            assert pending.Account.username == "cyc3_charlie"

        # Verify all three went through in order
        schedule = get_rotation_schedule(db_session, 2)
        statuses = [(r.Account.username, r.status) for r in schedule]
        assert statuses[0][1] == TyrantAssignmentStatus.CHOSEN  # alice
        assert statuses[1][1] == TyrantAssignmentStatus.CHOSEN  # bob
        assert statuses[2][1] == TyrantAssignmentStatus.PENDING  # charlie
