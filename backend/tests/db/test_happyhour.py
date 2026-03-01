"""Tests for happy hour database operations."""

from datetime import datetime, UTC, timedelta

from db.functions import (
    create_account,
    create_location,
    get_all_locations,
    get_location_by_id,
    get_open_locations,
    create_event,
    get_all_events,
    get_event_by_id,
    get_upcoming_event,
    get_random_previous_location,
    create_tyrant_assignment,
    create_cycle_rotation,
    get_current_pending_assignment,
    get_next_scheduled_assignment,
    get_on_deck_assignment,
    get_rotation_schedule,
    activate_assignment,
    get_current_cycle_number,
    get_consecutive_misses,
    mark_assignment_chosen,
    mark_assignment_missed,
    remove_claim_from_account,
)
from models.account import Account
from typing import Any
from models.happyhour.location import Location
from sqlalchemy.orm import Session
from models import ExternalAuthProvider, AccountClaims
from models.enums import TyrantAssignmentStatus


def _make_location(s: Session, name: str = "Test Bar", **overrides: Any) -> Location:
    """Helper to create a test location.

    :param s: Active SQLAlchemy session.
    :type s: Session
    :param name: Display name.
    :type name: str
    :param overrides: Keyword overrides for model fields.
    :type overrides: dict[str, Any]
    :returns: Persisted location row.
    :rtype: Location
    """
    defaults = dict(
        Name=name,
        URL="https://testbar.com",
        AddressRaw="123 Test St, Testville, TS 12345",
        Number=123,
        StreetName="Test St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    return create_location(s, **defaults)


def _make_tyrant(s: Session, name: str = "tyrant") -> Account:
    """Helper to create a user who schedules events.

    :param s: Active SQLAlchemy session.
    :type s: Session
    :param name: Display name.
    :type name: str
    :returns: Persisted account with tyrant claims.
    :rtype: Account
    """
    act = create_account(
        name,
        f"{name}@test.com",
        ExternalAuthProvider.test,
        name,
        claims=AccountClaims.HAPPY_HOUR,
    )
    s.add(act)
    s.commit()
    return act


class TestLocations:
    """Verify happy-hour location CRUD operations."""

    def test_create_location(self, db_session: Session) -> None:
        """Verify a location is created with the expected defaults.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session)
        assert loc.id is not None
        assert loc.Name == "Test Bar"
        assert loc.Closed is False

    def test_get_all_locations(self, db_session: Session) -> None:
        """Verify all locations are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_location(db_session, name="Bar A")
        _make_location(db_session, name="Bar B")
        locs = get_all_locations(db_session)
        assert len(locs) >= 2

    def test_get_location_by_id(self, db_session: Session) -> None:
        """Verify a location can be fetched by primary key.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Find Me")
        found = get_location_by_id(db_session, loc.id)
        assert found is not None
        assert found.Name == "Find Me"

    def test_get_location_not_found(self, db_session: Session) -> None:
        """Verify ``None`` is returned for a non-existent location.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        assert get_location_by_id(db_session, 99999) is None

    def test_get_open_locations(self, db_session: Session) -> None:
        """Verify closed locations are excluded from the open list.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_location(db_session, name="Open Bar")
        _closed = _make_location(db_session, name="Closed Bar", Closed=True)
        open_locs = get_open_locations(db_session)
        names = [loc.Name for loc in open_locs]
        assert "Open Bar" in names
        assert "Closed Bar" not in names

    def test_close_location(self, db_session: Session) -> None:
        """Verify a location can be marked as closed.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Soon Closed")
        loc.Closed = True
        db_session.commit()
        db_session.refresh(loc)
        assert loc.Closed is True


class TestEvents:
    """Verify happy-hour event CRUD operations."""

    def test_create_event(self, db_session: Session) -> None:
        """Verify an event is created with the expected attributes.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Event Bar")
        tyrant = _make_tyrant(db_session, "evttyrant")
        event = create_event(
            db_session,
            location_id=loc.id,
            when=datetime.now(UTC) + timedelta(days=1),
            tyrant_id=tyrant.id,
            description="Test happy hour",
        )
        assert event.id is not None
        assert event.Description == "Test happy hour"
        assert event.AutoSelected is False

    def test_get_all_events(self, db_session: Session) -> None:
        """Verify all events are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="All Events Bar")
        tyrant = _make_tyrant(db_session, "allevt")
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=1),
            tyrant_id=tyrant.id,
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=8),
            tyrant_id=tyrant.id,
        )
        events = get_all_events(db_session)
        assert len(events) >= 2

    def test_get_event_by_id(self, db_session: Session) -> None:
        """Verify an event can be fetched by primary key.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="ID Event Bar")
        tyrant = _make_tyrant(db_session, "idevt")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(hours=1),
            tyrant_id=tyrant.id,
        )
        found = get_event_by_id(db_session, event.id)
        assert found is not None
        assert found.id == event.id

    def test_get_upcoming_event(self, db_session: Session) -> None:
        """Verify the next upcoming event is returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Upcoming Bar")
        tyrant = _make_tyrant(db_session, "upcomevt")
        future_time = datetime.now(UTC) + timedelta(days=7)
        create_event(db_session, loc.id, future_time, tyrant_id=tyrant.id)
        upcoming = get_upcoming_event(db_session)
        assert upcoming is not None

    def test_auto_selected_event(self, db_session: Session) -> None:
        """Verify the ``AutoSelected`` flag is persisted.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Auto Bar")
        tyrant = _make_tyrant(db_session, "autoevt")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=1),
            tyrant_id=tyrant.id,
            auto_selected=True,
        )
        assert event.AutoSelected is True


class TestRandomPreviousLocation:
    """Verify random location selection from previous events."""

    def test_no_previous_events(self, db_session: Session) -> None:
        """Verify ``None`` when there are no previous events.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        result = get_random_previous_location(db_session)
        assert result is None

    def test_returns_open_location(self, db_session: Session) -> None:
        """Verify an open location is returned from past events.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Random Bar")
        tyrant = _make_tyrant(db_session, "randtyrant")
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=7),
            tyrant_id=tyrant.id,
        )
        result = get_random_previous_location(db_session)
        assert result is not None
        assert result.Closed is False

    def test_excludes_closed_locations(self, db_session: Session) -> None:
        """Verify closed locations are excluded from random selection.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Closed Random", Closed=True)
        tyrant = _make_tyrant(db_session, "closedrand")
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=7),
            tyrant_id=tyrant.id,
        )

        # Only the closed location has events — should return None
        result = get_random_previous_location(db_session)
        # Could be None or an open one from another test, just verify if returned it's open
        if result is not None:
            assert result.Closed is False


class TestTyrantRotation:
    """Tests for tyrant rotation database functions."""

    def _make_admin(self, s: Session, name: str) -> Account:
        """Create a test admin with ``HAPPY_HOUR_TYRANT`` claims.

        :param s: Active database session.
        :type s: Session
        :param name: Username.
        :type name: str
        :returns: The persisted account.
        :rtype: Account
        """
        act = create_account(
            name,
            f"{name}@test.com",
            ExternalAuthProvider.test,
            name,
            claims=AccountClaims.HAPPY_HOUR_TYRANT | AccountClaims.HAPPY_HOUR,
        )
        s.add(act)
        s.commit()
        return act

    def test_create_tyrant_assignment(self, db_session: Session) -> None:
        """Verify a new tyrant assignment is persisted as ``SCHEDULED`` by default.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_create")
        assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
        )
        assert assignment.id is not None
        assert assignment.account_id == admin.id
        assert assignment.cycle == 1
        assert assignment.position == 0
        assert assignment.status == TyrantAssignmentStatus.SCHEDULED
        assert assignment.deadline_at is None

    def test_get_current_pending_assignment(self, db_session: Session) -> None:
        """Verify the current pending assignment is returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_pending")
        create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=5),
            status=TyrantAssignmentStatus.PENDING,
        )
        pending = get_current_pending_assignment(db_session)
        assert pending is not None
        assert pending.account_id == admin.id

    def test_get_current_pending_returns_none_when_all_resolved(
        self, db_session: Session
    ) -> None:
        """Verify ``None`` when all assignments are resolved.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_none")
        a = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=5),
            status=TyrantAssignmentStatus.PENDING,
        )
        mark_assignment_chosen(db_session, a.id)
        pending = get_current_pending_assignment(db_session)
        assert pending is None

    def test_get_current_cycle_number_default(self, db_session: Session) -> None:
        """When no assignments exist, cycle defaults to 1.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        cycle = get_current_cycle_number(db_session)
        assert cycle == 1

    def test_get_current_cycle_number(self, db_session: Session) -> None:
        """Verify the current cycle number reflects the latest assignment.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_cycnum")
        create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=3,
            position=0,
            assigned_at=datetime.now(UTC),
        )
        assert get_current_cycle_number(db_session) == 3

    def test_mark_assignment_chosen(self, db_session: Session) -> None:
        """Verify an assignment status transitions to ``CHOSEN``.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_chosen")
        a = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=5),
            status=TyrantAssignmentStatus.PENDING,
        )
        mark_assignment_chosen(db_session, a.id)
        db_session.refresh(a)
        assert a.status == TyrantAssignmentStatus.CHOSEN

    def test_mark_assignment_missed(self, db_session: Session) -> None:
        """Verify an assignment status transitions to ``MISSED``.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_missed")
        a = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC) + timedelta(days=5),
            status=TyrantAssignmentStatus.PENDING,
        )
        mark_assignment_missed(db_session, a.id)
        db_session.refresh(a)
        assert a.status == TyrantAssignmentStatus.MISSED

    def test_get_consecutive_misses_zero(self, db_session: Session) -> None:
        """Verify zero consecutive misses for a fresh admin.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_nomiss")
        assert get_consecutive_misses(db_session, admin.id) == 0

    def test_get_consecutive_misses_counts_streak(self, db_session: Session) -> None:
        """Verify consecutive misses are counted correctly.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_streak")
        for i in range(3):
            a = create_tyrant_assignment(
                db_session,
                admin.id,
                cycle=1,
                position=i,
                assigned_at=datetime.now(UTC) - timedelta(days=21 - i * 7),
                deadline_at=datetime.now(UTC) - timedelta(days=16 - i * 7),
                status=TyrantAssignmentStatus.PENDING,
            )
            a.status = TyrantAssignmentStatus.MISSED
            db_session.commit()
        assert get_consecutive_misses(db_session, admin.id) == 3

    def test_get_consecutive_misses_resets_on_chosen(self, db_session: Session) -> None:
        """Verify a ``CHOSEN`` assignment resets the miss streak.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_reset")
        # miss, chosen, miss => 1 consecutive miss
        for i, st in enumerate(
            [
                TyrantAssignmentStatus.MISSED,
                TyrantAssignmentStatus.CHOSEN,
                TyrantAssignmentStatus.MISSED,
            ]
        ):
            a = create_tyrant_assignment(
                db_session,
                admin.id,
                cycle=1,
                position=i,
                assigned_at=datetime.now(UTC) - timedelta(days=21 - i * 7),
                deadline_at=datetime.now(UTC) - timedelta(days=16 - i * 7),
                status=TyrantAssignmentStatus.PENDING,
            )
            a.status = st
            db_session.commit()
        assert get_consecutive_misses(db_session, admin.id) == 1

    def test_create_cycle_rotation(self, db_session: Session) -> None:
        """Verify a full cycle rotation is created with shuffled positions.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin1 = self._make_admin(db_session, "cyc_a")
        admin2 = self._make_admin(db_session, "cyc_b")
        admin3 = self._make_admin(db_session, "cyc_c")
        rotations = create_cycle_rotation(
            db_session,
            [admin1, admin2, admin3],
            cycle=1,
            now=datetime.now(UTC),
        )
        assert len(rotations) == 3
        positions = [r.position for r in rotations]
        assert sorted(positions) == [0, 1, 2]
        assert all(r.status == TyrantAssignmentStatus.SCHEDULED for r in rotations)
        assert all(r.deadline_at is None for r in rotations)

    def test_get_next_scheduled_assignment(self, db_session: Session) -> None:
        """Verify the next SCHEDULED assignment is returned by position.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin1 = self._make_admin(db_session, "sched_a")
        admin2 = self._make_admin(db_session, "sched_b")
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.PENDING,
            deadline_at=datetime.now(UTC) + timedelta(days=5),
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC),
        )
        nxt = get_next_scheduled_assignment(db_session, cycle=1)
        assert nxt is not None
        assert nxt.account_id == admin2.id
        assert nxt.position == 1

    def test_get_on_deck_assignment(self, db_session: Session) -> None:
        """Verify the on-deck assignment is the next SCHEDULED after current.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin1 = self._make_admin(db_session, "deck_a")
        admin2 = self._make_admin(db_session, "deck_b")
        admin3 = self._make_admin(db_session, "deck_c")
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.PENDING,
            deadline_at=datetime.now(UTC) + timedelta(days=5),
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC),
        )
        create_tyrant_assignment(
            db_session,
            admin3.id,
            cycle=1,
            position=2,
            assigned_at=datetime.now(UTC),
        )
        on_deck = get_on_deck_assignment(db_session, cycle=1, current_position=0)
        assert on_deck is not None
        assert on_deck.account_id == admin2.id

    def test_activate_assignment(self, db_session: Session) -> None:
        """Verify a SCHEDULED assignment transitions to PENDING with deadline.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "act_admin")
        a = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
        )
        assert a.status == TyrantAssignmentStatus.SCHEDULED
        assert a.deadline_at is None
        deadline = datetime.now(UTC) + timedelta(days=5)
        activate_assignment(db_session, a.id, deadline)
        db_session.refresh(a)
        assert a.status == TyrantAssignmentStatus.PENDING
        assert a.deadline_at.replace(tzinfo=None) == deadline.replace(tzinfo=None)

    def test_get_rotation_schedule(self, db_session: Session) -> None:
        """Verify the full rotation schedule is returned in position order.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin1 = self._make_admin(db_session, "rot_sched_a")
        admin2 = self._make_admin(db_session, "rot_sched_b")
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC),
        )
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
        )
        schedule = get_rotation_schedule(db_session, 1)
        assert len(schedule) == 2
        assert schedule[0].account_id == admin1.id
        assert schedule[1].account_id == admin2.id

    def test_remove_claim_from_account(self, db_session: Session) -> None:
        """Verify a single claim flag is removed while preserving others.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        admin = self._make_admin(db_session, "rot_remove")
        assert admin.claims & AccountClaims.HAPPY_HOUR_TYRANT
        remove_claim_from_account(db_session, admin.id, AccountClaims.HAPPY_HOUR_TYRANT)
        db_session.refresh(admin)
        assert not (admin.claims & AccountClaims.HAPPY_HOUR_TYRANT)
        # Other claims preserved
        assert admin.claims & AccountClaims.HAPPY_HOUR

    def test_create_event_with_null_tyrant(self, db_session: Session) -> None:
        """Events can be created with tyrant_id=None.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="System Bar")
        event = create_event(
            db_session,
            location_id=loc.id,
            when=datetime.now(UTC) + timedelta(days=1),
            tyrant_id=None,
            auto_selected=True,
        )
        assert event.id is not None
        assert event.TyrantID is None
        assert event.Tyrant is None
        assert event.AutoSelected is True


class TestTyrantRotationSetterFixed:
    """The assignment_status setter now correctly stores the enum value,
    allowing successful commit."""

    def _make_admin(self, s: Session, name: str) -> Account:
        """Create a test admin with ``HAPPY_HOUR_TYRANT`` claims.

        :param s: Active database session.
        :type s: Session
        :param name: Username.
        :type name: str
        :returns: The persisted account.
        :rtype: Account
        """
        act = create_account(
            name,
            f"{name}@test.com",
            ExternalAuthProvider.test,
            name,
            claims=AccountClaims.HAPPY_HOUR_TYRANT | AccountClaims.HAPPY_HOUR,
        )
        s.add(act)
        s.commit()
        return act

    def test_setter_commits_successfully(self, db_session: Session) -> None:
        """Verify the ``assignment_status`` property setter commits without error.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """

        admin = self._make_admin(db_session, "setter_test")
        assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
        )

        # Using the property setter now works correctly
        assignment.status = TyrantAssignmentStatus.CHOSEN
        db_session.commit()
        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.CHOSEN, (
            "Setter should store the enum directly, allowing successful commit"
        )
