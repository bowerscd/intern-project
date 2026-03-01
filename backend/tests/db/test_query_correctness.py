"""Tests for query correctness: missing upper bounds, N+1 patterns."""

from datetime import datetime, UTC, timedelta

from db.functions import (
    create_account,
    create_location,
    create_event,
    get_events_this_week,
)
from typing import Any
from models.happyhour.location import Location
from sqlalchemy.orm import Session
from models import ExternalAuthProvider


class TestEventsThisWeekUpperBound:
    """
    get_events_this_week now has an upper bound, excluding events
    far in the future from the current week's results.
    """

    def test_excludes_far_future_events(self, db_session: Session) -> None:
        """An event 6 months from now should NOT appear in 'this week'.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Future Bar")
        a = create_account("qb_a", "qb_a@t.com", ExternalAuthProvider.test, "qb_a")
        db_session.add(a)
        db_session.commit()

        now = datetime.now(UTC)
        far_future = now + timedelta(days=180)

        create_event(db_session, loc.id, when=far_future, tyrant_id=a.id)

        results = get_events_this_week(db_session, now)
        threshold = now + timedelta(days=30)
        future_events = [
            e
            for e in results
            if (e.When.replace(tzinfo=UTC) if e.When.tzinfo is None else e.When)
            > threshold
        ]

        assert len(future_events) == 0, (
            "get_events_this_week should exclude events 6 months out"
        )


def _make_location(s: Session, name: str = "Query Bar", **overrides: Any) -> Location:
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
        URL="https://querybar.com",
        AddressRaw="123 Query St",
        Number=123,
        StreetName="Query St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    return create_location(s, **defaults)
