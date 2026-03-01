"""Tests for the scheduler module — tyrant rotation and auto-select."""

import pytest
import logging
from datetime import datetime, UTC, timedelta
from unittest.mock import patch, MagicMock

from db import Database
from db.functions import (
    create_account,
    create_location,
    create_event,
    get_all_events,
    create_tyrant_assignment,
    get_current_pending_assignment,
    get_rotation_schedule,
)
from models.account import Account
from typing import Any
from models.happyhour.location import Location
from sqlalchemy.orm import Session
from models import ExternalAuthProvider, AccountClaims, PhoneProvider
from models.enums import TyrantAssignmentStatus


def _make_location(s: Session, name: str = "Sched Bar", **overrides: Any) -> Location:
    """Create a test happy-hour location.

    :param s: Active database session.
    :type s: Session
    :param name: Location name.
    :type name: str
    :returns: The persisted location.
    :rtype: Location
    """
    defaults = dict(
        Name=name,
        URL="https://schedbar.com",
        AddressRaw="123 Sched St",
        Number=123,
        StreetName="Sched St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    loc = create_location(s, **defaults)
    s.commit()
    return loc


def _make_user(
    s: Session,
    name: str,
    claims: AccountClaims = AccountClaims.HAPPY_HOUR,
    phone: str | None = None,
    phone_provider: PhoneProvider = PhoneProvider.NONE,
) -> Account:
    """Create a test user account with the given claims.

    :param s: Active database session.
    :type s: Session
    :param name: Username.
    :type name: str
    :param claims: Account claim flags.
    :type claims: AccountClaims
    :param phone: Optional phone number.
    :type phone: str | None
    :param phone_provider: SMS provider.
    :type phone_provider: PhoneProvider
    :returns: The persisted account.
    :rtype: Account
    """
    act = create_account(
        name,
        f"{name}@test.com",
        ExternalAuthProvider.test,
        name,
        claims=claims,
        phone=phone,
        phone_provider=phone_provider,
    )
    s.add(act)
    s.commit()
    return act


class TestGetScheduler:
    """Verify :func:`~scheduler.get_scheduler` singleton behaviour."""

    def test_get_scheduler_returns_singleton(self) -> None:
        """Verify consecutive calls return the same scheduler instance."""
        import scheduler

        scheduler.scheduler = None
        s1 = scheduler.get_scheduler()
        s2 = scheduler.get_scheduler()
        assert s1 is s2
        scheduler.scheduler = None

    def test_get_scheduler_creates_async_scheduler(self) -> None:
        """Verify the scheduler is an :class:`AsyncIOScheduler`."""
        import scheduler
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler.scheduler = None
        s = scheduler.get_scheduler()
        assert isinstance(s, AsyncIOScheduler)
        scheduler.scheduler = None


class TestAssignTyrant:
    """Verify :func:`~scheduler.assign_tyrant` cycle-based rotation logic."""

    @pytest.mark.asyncio
    async def test_creates_full_cycle_on_first_run(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should create a full rotation cycle with all admins on first run.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        admin1 = _make_user(
            db_session, "admin_a", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        admin2 = _make_user(
            db_session, "admin_b", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )

        # Mock shuffle to get deterministic order: [admin_a, admin_b]
        def no_shuffle(lst: list) -> None:
            lst.sort(key=lambda a: a.id)

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            with caplog.at_level(logging.INFO):
                from scheduler import assign_tyrant

                await assign_tyrant()

            assert "Created new rotation cycle" in caplog.text

        # Full rotation created: 2 assignments
        assignments = get_rotation_schedule(db_session, cycle=2)
        assert len(assignments) == 2

        # First assignment activated to PENDING
        pending = get_current_pending_assignment(db_session)
        assert pending is not None
        assert pending.account_id == admin1.id
        assert pending.status == TyrantAssignmentStatus.PENDING
        assert pending.deadline_at is not None

        # Second still SCHEDULED
        assert assignments[1].account_id == admin2.id
        assert assignments[1].status == TyrantAssignmentStatus.SCHEDULED

    @pytest.mark.asyncio
    async def test_activates_next_scheduled_in_cycle(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should activate the next SCHEDULED assignment in the current cycle.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        admin1 = _make_user(db_session, "rot_a", claims=AccountClaims.HAPPY_HOUR_TYRANT)
        admin2 = _make_user(db_session, "rot_b", claims=AccountClaims.HAPPY_HOUR_TYRANT)

        # Simulate: admin1 already done (CHOSEN), admin2 still SCHEDULED
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=7),
            deadline_at=datetime.now(UTC) - timedelta(days=2),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC) - timedelta(days=7),
        )
        db_session.commit()

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
        ):
            from scheduler import assign_tyrant

            await assign_tyrant()

        pending = get_current_pending_assignment(db_session)
        assert pending is not None
        assert pending.account_id == admin2.id

    @pytest.mark.asyncio
    async def test_starts_new_cycle_when_all_assigned(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should start a new cycle when all admins have been assigned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        admin1 = _make_user(db_session, "cyc_a", claims=AccountClaims.HAPPY_HOUR_TYRANT)
        admin2 = _make_user(db_session, "cyc_b", claims=AccountClaims.HAPPY_HOUR_TYRANT)

        # Both assigned in cycle 1 (all CHOSEN, none SCHEDULED)
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=14),
            deadline_at=datetime.now(UTC) - timedelta(days=9),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC) - timedelta(days=7),
            deadline_at=datetime.now(UTC) - timedelta(days=2),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        db_session.commit()

        def no_shuffle(lst: list) -> None:
            lst.sort(key=lambda a: a.id)

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            with caplog.at_level(logging.INFO):
                from scheduler import assign_tyrant

                await assign_tyrant()

            assert "cycle 2" in caplog.text

        pending = get_current_pending_assignment(db_session)
        assert pending is not None
        assert pending.cycle == 2
        assert pending.account_id == admin1.id

    @pytest.mark.asyncio
    async def test_single_admin_always_assigned(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With only 1 admin, they get assigned every week (rotation completes each time).

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        admin = _make_user(
            db_session, "solo_admin", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )

        # Simulate solo admin already assigned in cycle 1 (no SCHEDULED remain)
        create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=7),
            deadline_at=datetime.now(UTC) - timedelta(days=2),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        db_session.commit()

        def no_shuffle(lst: list) -> None:
            pass  # single-element list — no change

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            from scheduler import assign_tyrant

            await assign_tyrant()

        pending = get_current_pending_assignment(db_session)
        assert pending is not None
        assert pending.account_id == admin.id
        assert pending.cycle == 2

    @pytest.mark.asyncio
    async def test_no_admins_logs_warning(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If no HAPPY_HOUR_TYRANT users, logs a warning and skips.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        with patch("db.Database", return_value=database):
            with caplog.at_level(logging.WARNING):
                from scheduler import assign_tyrant

                await assign_tyrant()

            assert "No HAPPY_HOUR_TYRANT users found" in caplog.text

    @pytest.mark.asyncio
    async def test_notifies_assigned_tyrant(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should call notify_tyrant_assigned for the selected admin.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        _make_user(db_session, "notif_admin", claims=AccountClaims.HAPPY_HOUR_TYRANT)

        def no_shuffle(lst: list) -> None:
            pass

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned") as mock_notify,
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            from scheduler import assign_tyrant

            await assign_tyrant()

            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_notifies_on_deck_person(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should call notify_tyrant_on_deck for the next person in rotation.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        _make_user(db_session, "ondeck_a", claims=AccountClaims.HAPPY_HOUR_TYRANT)
        _make_user(db_session, "ondeck_b", claims=AccountClaims.HAPPY_HOUR_TYRANT)

        def no_shuffle(lst: list) -> None:
            lst.sort(key=lambda a: a.id)

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck") as mock_on_deck,
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            from scheduler import assign_tyrant

            await assign_tyrant()

            mock_on_deck.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_on_deck_for_last_in_rotation(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should not call on_deck when activating the last person in the cycle.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        admin1 = _make_user(
            db_session, "last_a", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        admin2 = _make_user(
            db_session, "last_b", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )

        # admin1 done, admin2 is the last SCHEDULED
        create_tyrant_assignment(
            db_session,
            admin1.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=7),
            deadline_at=datetime.now(UTC) - timedelta(days=2),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        create_tyrant_assignment(
            db_session,
            admin2.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC) - timedelta(days=7),
        )
        db_session.commit()

        with (
            patch("db.Database", return_value=database),
            patch("mail.outgoing.notify_tyrant_assigned"),
            patch("mail.outgoing.notify_tyrant_on_deck") as mock_on_deck,
        ):
            from scheduler import assign_tyrant

            await assign_tyrant()

            mock_on_deck.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_error_does_not_crash(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If notification fails, error is logged but assignment still happens.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        _make_user(db_session, "nfail_admin", claims=AccountClaims.HAPPY_HOUR_TYRANT)

        def no_shuffle(lst: list) -> None:
            pass

        with (
            patch("db.Database", return_value=database),
            patch(
                "mail.outgoing.notify_tyrant_assigned",
                side_effect=Exception("SMTP down"),
            ),
            patch("mail.outgoing.notify_tyrant_on_deck"),
            patch("random.shuffle", side_effect=no_shuffle),
        ):
            with caplog.at_level(logging.ERROR):
                from scheduler import assign_tyrant

                await assign_tyrant()

            assert "Failed to notify tyrant" in caplog.text

        # Assignment should still exist
        pending = get_current_pending_assignment(db_session)
        assert pending is not None


class TestAutoSelectHappyHour:
    """Verify :func:`~scheduler.auto_select_happy_hour` fallback logic."""

    @pytest.mark.asyncio
    async def test_skips_when_event_exists_this_week(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If an event already exists this week, auto_select should skip.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Already Picked")
        tyrant = _make_user(
            db_session, "tyrant_skip", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        create_event(db_session, loc.id, datetime.now(UTC), tyrant_id=tyrant.id)
        db_session.commit()

        with patch("db.Database", return_value=database):
            with caplog.at_level(logging.INFO):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "already decided" in caplog.text

    @pytest.mark.asyncio
    async def test_marks_pending_assignment_chosen_when_event_exists(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If an event exists and there's a pending assignment, mark it chosen.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Chosen Bar")
        admin = _make_user(
            db_session, "chosen_admin", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        create_event(db_session, loc.id, datetime.now(UTC), tyrant_id=admin.id)

        assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=3),
            deadline_at=datetime.now(UTC) + timedelta(hours=1),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        with patch("db.Database", return_value=database):
            from scheduler import auto_select_happy_hour

            await auto_select_happy_hour()

        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.CHOSEN

    @pytest.mark.asyncio
    async def test_skips_when_no_previous_locations(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If there are no previous locations, should warn and skip.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        with patch("db.Database", return_value=database):
            with caplog.at_level(logging.WARNING):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "No previous locations" in caplog.text

    @pytest.mark.asyncio
    async def test_auto_selects_with_null_tyrant(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Auto-selected events should have TyrantID=None.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Auto Select Bar")
        admin = _make_user(
            db_session, "auto_admin", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        # Create a past event so the location is in the "previous" pool
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=admin.id,
        )
        db_session.commit()

        with (
            patch("mail.outgoing.notify_happy_hour_users") as mock_notify,
            patch("db.Database", return_value=database),
        ):
            with caplog.at_level(logging.INFO):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "Auto-selected happy hour" in caplog.text
            events = get_all_events(db_session)
            auto_events = [e for e in events if e.AutoSelected]
            assert len(auto_events) == 1
            assert auto_events[0].TyrantID is None
            assert auto_events[0].Description.startswith("Auto-selected:")
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_marks_pending_assignment_missed(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If no event exists and there's a pending assignment, mark it missed.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Miss Bar")
        admin = _make_user(
            db_session, "miss_admin", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=admin.id,
        )

        assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=5),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        with (
            patch("mail.outgoing.notify_happy_hour_users"),
            patch("db.Database", return_value=database),
        ):
            with caplog.at_level(logging.WARNING):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "missed their deadline" in caplog.text

        db_session.refresh(assignment)
        assert assignment.status == TyrantAssignmentStatus.MISSED

    @pytest.mark.asyncio
    async def test_removes_admin_after_3_consecutive_misses(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """After 3 consecutive misses, HAPPY_HOUR_TYRANT claim is removed.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Strike3 Bar")
        admin = _make_user(
            db_session,
            "strike3",
            claims=AccountClaims.HAPPY_HOUR_TYRANT | AccountClaims.HAPPY_HOUR,
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=admin.id,
        )

        # Record 2 prior misses
        for i in range(2):
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

        # Create a 3rd pending assignment (this will be the 3rd miss)
        _assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=2,
            assigned_at=datetime.now(UTC) - timedelta(days=5),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        with (
            patch("mail.outgoing.notify_happy_hour_users"),
            patch("db.Database", return_value=database),
        ):
            with caplog.at_level(logging.WARNING):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "Removed HAPPY_HOUR_TYRANT" in caplog.text

        db_session.refresh(admin)
        assert not (admin.claims & AccountClaims.HAPPY_HOUR_TYRANT)
        # Should still have HAPPY_HOUR
        assert admin.claims & AccountClaims.HAPPY_HOUR

    @pytest.mark.asyncio
    async def test_no_removal_at_2_consecutive_misses(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """At 2 consecutive misses, admin is NOT removed.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Strike2 Bar")
        admin = _make_user(
            db_session,
            "strike2",
            claims=AccountClaims.HAPPY_HOUR_TYRANT | AccountClaims.HAPPY_HOUR,
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=admin.id,
        )

        # Record 1 prior miss
        a = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC) - timedelta(days=14),
            deadline_at=datetime.now(UTC) - timedelta(days=9),
            status=TyrantAssignmentStatus.PENDING,
        )
        a.status = TyrantAssignmentStatus.MISSED
        db_session.commit()

        # 2nd pending assignment
        _assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=1,
            assigned_at=datetime.now(UTC) - timedelta(days=5),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        with (
            patch("mail.outgoing.notify_happy_hour_users"),
            patch("db.Database", return_value=database),
        ):
            with caplog.at_level(logging.WARNING):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

        db_session.refresh(admin)
        # Still has HAPPY_HOUR_TYRANT — only 2 misses
        assert admin.claims & AccountClaims.HAPPY_HOUR_TYRANT

    @pytest.mark.asyncio
    async def test_consecutive_misses_reset_by_chosen(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A CHOSEN assignment resets the consecutive miss streak.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Reset Bar")
        admin = _make_user(
            db_session,
            "reset_admin",
            claims=AccountClaims.HAPPY_HOUR_TYRANT | AccountClaims.HAPPY_HOUR,
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=admin.id,
        )

        # 2 misses then 1 chosen then 1 pending => only 1 consecutive miss from the end
        for i, st in enumerate(
            [
                TyrantAssignmentStatus.MISSED,
                TyrantAssignmentStatus.MISSED,
                TyrantAssignmentStatus.CHOSEN,
            ]
        ):
            a = create_tyrant_assignment(
                db_session,
                admin.id,
                cycle=1,
                position=i,
                assigned_at=datetime.now(UTC) - timedelta(days=28 - i * 7),
                deadline_at=datetime.now(UTC) - timedelta(days=23 - i * 7),
                status=TyrantAssignmentStatus.PENDING,
            )
            a.status = st
            db_session.commit()

        # Current pending
        _assignment = create_tyrant_assignment(
            db_session,
            admin.id,
            cycle=1,
            position=3,
            assigned_at=datetime.now(UTC) - timedelta(days=5),
            deadline_at=datetime.now(UTC) - timedelta(hours=1),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        with (
            patch("mail.outgoing.notify_happy_hour_users"),
            patch("db.Database", return_value=database),
        ):
            from scheduler import auto_select_happy_hour

            await auto_select_happy_hour()

        db_session.refresh(admin)
        # Only 1 consecutive miss (after a CHOSEN), so NOT removed
        assert admin.claims & AccountClaims.HAPPY_HOUR_TYRANT

    @pytest.mark.asyncio
    async def test_notification_error_caught(
        self, db_session: Session, database: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If notification sending fails, error is logged but doesn't crash.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        :param database: Started database instance.
        :type database: Database
        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        loc = _make_location(db_session, name="Notify Fail Bar")
        admin = _make_user(
            db_session, "notifyfail", claims=AccountClaims.HAPPY_HOUR_TYRANT
        )
        create_event(
            db_session,
            loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=admin.id,
        )
        db_session.commit()

        with (
            patch(
                "mail.outgoing.notify_happy_hour_users",
                side_effect=Exception("SMTP down"),
            ),
            patch("db.Database", return_value=database),
        ):
            with caplog.at_level(logging.ERROR):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "Failed to send auto-select notifications" in caplog.text

    @pytest.mark.asyncio
    async def test_db_error_caught(self, caplog: pytest.LogCaptureFixture) -> None:
        """If the database fails entirely, error is logged.

        :param caplog: Captured log records.
        :type caplog: pytest.LogCaptureFixture
        """
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(side_effect=Exception("DB exploded"))
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.session = MagicMock(return_value=mock_db)

        with patch("db.Database", return_value=mock_db):
            with caplog.at_level(logging.ERROR):
                from scheduler import auto_select_happy_hour

                await auto_select_happy_hour()

            assert "Error during happy hour auto-select" in caplog.text
