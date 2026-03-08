"""Additional db/functions tests for edge cases and missing coverage."""

import pytest
from datetime import datetime, UTC, timedelta

from db.functions import (
    create_account,
    create_receipt,
    get_records_for_user,
    get_records_between_users,
    get_timebound_records,
    get_timebound_records_between_users,
    get_timebound_records_for_user,
    get_events_this_week,
    get_random_previous_location,
    get_accounts_with_claim,
    create_location,
    create_event,
)
from typing import Any
from models.happyhour.location import Location
from sqlalchemy.orm import Session
from models import ExternalAuthProvider, AccountClaims


def _make_users(s: Session, names: list[str]) -> None:
    """Create one or more test user accounts.

    :param s: Active database session.
    :type s: Session
    :param names: Usernames to create.
    :type names: list[str]
    """
    for name in names:
        act = create_account(name, f"{name}@test.com", ExternalAuthProvider.test, name)
        s.add(act)
    s.commit()


def _make_location(s: Session, name: str = "Edge Bar", **overrides: Any) -> Location:
    """Create a test location with sensible defaults.

    :param s: Active database session.
    :type s: Session
    :param name: Location name.
    :type name: str
    :returns: The persisted location.
    :rtype: Location
    """
    defaults = dict(
        Name=name,
        URL="https://edgebar.com",
        AddressRaw="789 Edge St",
        Number=789,
        StreetName="Edge St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    return create_location(s, **defaults)


class TestRecordsBetweenUsersEdgeCases:
    """Cover get_records_between_users error paths."""

    def test_nonexistent_user1(self, db_session: Session) -> None:
        """Verify an error when the first user does not exist.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["real1"])
        with pytest.raises(ValueError, match="does not exist"):
            get_records_between_users(db_session, "ghost1", "real1")

    def test_nonexistent_user2(self, db_session: Session) -> None:
        """Verify an error when the second user does not exist.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["real2"])
        with pytest.raises(ValueError, match="does not exist"):
            get_records_between_users(db_session, "real2", "ghost2")

    def test_with_limit(self, db_session: Session) -> None:
        """Verify the *limit* parameter caps the between-users result set.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["blma", "blmb"])
        for i in range(5):
            create_receipt(db_session, "blma", "blmb", i + 1)

        records = get_records_between_users(db_session, "blma", "blmb", limit=2)
        assert len(records) == 2


class TestTimeboundRecordsBetweenUsers:
    """Cover get_timebound_records_between_users."""

    def test_basic(self, db_session: Session) -> None:
        """Verify records within the time window are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tbu1", "tbu2"])
        create_receipt(db_session, "tbu1", "tbu2", 5)

        now = datetime.now(UTC)
        records = get_timebound_records_between_users(
            db_session,
            "tbu1",
            "tbu2",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
        )
        assert len(records) == 1
        assert records[0].Credits == 5

    def test_outside_range(self, db_session: Session) -> None:
        """Verify records outside the time window are excluded.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tbo1", "tbo2"])
        create_receipt(db_session, "tbo1", "tbo2", 3)

        far_past = datetime(2000, 1, 1, tzinfo=UTC)
        records = get_timebound_records_between_users(
            db_session,
            "tbo1",
            "tbo2",
            start=far_past,
            end=far_past + timedelta(hours=1),
        )
        assert len(records) == 0

    def test_nonexistent_user1(self, db_session: Session) -> None:
        """Verify an error when the first user does not exist.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tbr1"])
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="does not exist"):
            get_timebound_records_between_users(
                db_session,
                "ghost",
                "tbr1",
                start=now,
                end=now + timedelta(hours=1),
            )

    def test_nonexistent_user2(self, db_session: Session) -> None:
        """Verify an error when the second user does not exist.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tbr2"])
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="does not exist"):
            get_timebound_records_between_users(
                db_session,
                "tbr2",
                "ghost",
                start=now,
                end=now + timedelta(hours=1),
            )

    def test_with_limit(self, db_session: Session) -> None:
        """Verify the *limit* parameter caps timebound between-users results.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tbl1", "tbl2"])
        for i in range(5):
            create_receipt(db_session, "tbl1", "tbl2", i + 1)

        now = datetime.now(UTC)
        records = get_timebound_records_between_users(
            db_session,
            "tbl1",
            "tbl2",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
            limit=3,
        )
        assert len(records) == 3


class TestRecordsForUserWithLimit:
    """Verify ``get_records_for_user`` honours the *limit* parameter."""

    def test_with_limit(self, db_session: Session) -> None:
        """Verify per-user records are capped by *limit*.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["rlma", "rlmb"])
        for i in range(5):
            create_receipt(db_session, "rlma", "rlmb", i + 1)

        records = get_records_for_user(db_session, "rlma", limit=2)
        assert len(records) == 2


class TestTimeboundRecordsWithLimit:
    """Verify ``get_timebound_records`` honours the *limit* parameter."""

    def test_timebound_records_with_limit(self, db_session: Session) -> None:
        """Verify timebound records are capped by *limit*.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["trlma", "trlmb"])
        for i in range(5):
            create_receipt(db_session, "trlma", "trlmb", i + 1)

        now = datetime.now(UTC)
        records = get_timebound_records(
            db_session,
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
            limit=2,
        )
        assert len(records) == 2


class TestTimeboundRecordsForUserWithLimit:
    """Verify ``get_timebound_records_for_user`` honours the *limit* parameter."""

    def test_with_limit(self, db_session: Session) -> None:
        """Verify timebound per-user records are capped by *limit*.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["trula", "trulb"])
        for i in range(5):
            create_receipt(db_session, "trula", "trulb", i + 1)

        now = datetime.now(UTC)
        records = get_timebound_records_for_user(
            db_session,
            "trula",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
            limit=2,
        )
        assert len(records) == 2


class TestEventsThisWeek:
    """Verify ``get_events_this_week`` window boundaries."""

    def test_events_after_wednesday_noon(self, db_session: Session) -> None:
        """Verify an event created now appears in this week's results.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Wed Bar")
        act = create_account(
            "weduser",
            "weduser@test.com",
            ExternalAuthProvider.test,
            "wu1",
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        # Create an event at the current time (within this week's window)
        _current_event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC),
            tyrant_id=act.id,
        )

        events = get_events_this_week(db_session, datetime.now(UTC))
        # We created an event "now" so it should be in this week
        assert len(events) >= 1

    def test_no_events_this_week(self, db_session: Session) -> None:
        """No events were created, should return empty.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        events = get_events_this_week(db_session, datetime.now(UTC))
        assert len(events) == 0

    def test_event_before_wednesday_cutoff(self, db_session: Session) -> None:
        """Events far in the past should not appear in this week.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Old Bar")
        act = create_account(
            "olduser",
            "old@test.com",
            ExternalAuthProvider.test,
            "ou1",
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        # Create an event far in the past
        create_event(
            db_session,
            loc.id,
            datetime(2020, 1, 1, tzinfo=UTC),
            tyrant_id=act.id,
        )

        events = get_events_this_week(db_session, datetime.now(UTC))
        assert len(events) == 0


class TestGetAccountsWithClaim:
    """Verify ``get_accounts_with_claim`` edge cases."""

    def test_no_matching_users(self, db_session: Session) -> None:
        """Verify an empty list when no accounts match the claim.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        results = get_accounts_with_claim(db_session, AccountClaims.ADMIN)
        assert len(results) == 0


class TestGetRandomPreviousLocationEdgeCases:
    """Verify ``get_random_previous_location`` skips closed and illegal venues."""

    def test_all_locations_closed(self, db_session: Session) -> None:
        """If all previous event locations are closed, return None.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="All Closed Bar", Closed=True)
        act = create_account(
            "closedlocuser",
            "cl@test.com",
            ExternalAuthProvider.test,
            "clu1",
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()
        create_event(
            db_session, loc.id, datetime.now(UTC) - timedelta(days=14), tyrant_id=act.id
        )

        result = get_random_previous_location(db_session)
        assert result is None

    def test_all_locations_illegal(self, db_session: Session) -> None:
        """If all previous event locations are illegal, return None.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="All Illegal Bar", Illegal=True)
        act = create_account(
            "illegallocuser",
            "il@test.com",
            ExternalAuthProvider.test,
            "ilu1",
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()
        create_event(
            db_session, loc.id, datetime.now(UTC) - timedelta(days=14), tyrant_id=act.id
        )

        result = get_random_previous_location(db_session)
        assert result is None

    def test_skips_illegal_returns_legal(self, db_session: Session) -> None:
        """Should skip illegal locations and return only legal ones.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        illegal_loc = _make_location(db_session, name="Illegal Bar", Illegal=True)
        legal_loc = _make_location(db_session, name="Legal Bar")
        act = create_account(
            "filteruser",
            "fi@test.com",
            ExternalAuthProvider.test,
            "fiu1",
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()
        create_event(
            db_session,
            illegal_loc.id,
            datetime.now(UTC) - timedelta(days=14),
            tyrant_id=act.id,
        )
        create_event(
            db_session,
            legal_loc.id,
            datetime.now(UTC) - timedelta(days=7),
            tyrant_id=act.id,
        )

        # With only one legal location, it must always be returned
        result = get_random_previous_location(db_session)
        assert result is not None
        assert result.id == legal_loc.id


class TestEventsThisWeekNoUpperBound:
    """
    get_events_this_week queries Event.When >= last_wed_noon with no upper
    bound. A far-future event (e.g. 90 days out) matches, making the
    scheduler think every week "already has an event".
    """

    def test_far_future_event_excluded_from_this_week(
        self, db_session: Session
    ) -> None:
        """An event 90 days in the future is excluded from get_events_this_week.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="FutureBar")
        event = create_event(
            db_session,
            location_id=loc.id,
            when=datetime.now(UTC) + timedelta(days=90),
        )

        events = get_events_this_week(db_session, datetime.now(UTC))
        event_ids = [e.id for e in events]
        assert event.id not in event_ids, (
            "Far-future event should be excluded by upper bound"
        )


class TestEventsThisWeekStaleEventFromPriorCycle:
    """
    A carry-over auto-selected event whose When falls this Friday will
    appear in get_events_this_week, potentially causing the scheduler to
    skip auto-selection and incorrectly mark a pending assignment as CHOSEN.
    """

    def test_auto_selected_event_from_prior_cycle_appears_this_week(
        self, db_session: Session
    ) -> None:
        """An auto-selected event within the current week window appears in results.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="EdgeBar")

        now = datetime.now(UTC)

        # Create an event at current time (guaranteed within this week's window)
        event = create_event(
            db_session,
            location_id=loc.id,
            when=now,
            auto_selected=True,
            description="Auto-selected from prior cycle",
        )

        events_this_week = get_events_this_week(db_session, now)
        event_ids = [e.id for e in events_this_week]
        assert event.id in event_ids, (
            "Event at current time should appear in this week's results"
        )
