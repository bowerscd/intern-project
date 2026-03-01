"""Tests for SqlValueEnum and classproperty in models.internal."""

import pytest
import time

from models.internal import SqlValueEnum, classproperty
from models.enums import PhoneProvider, AccountClaims

from db.functions import create_account, create_location
from models import ExternalAuthProvider, DBReceipt as Receipt
from typing import Any
from models.happyhour.location import Location
from sqlalchemy.orm import Session


class TestSqlValueEnum:
    """Cover SqlValueEnum edge cases."""

    def test_process_result_value_valid(self) -> None:
        """Test converting a stored value back to enum."""
        sve = SqlValueEnum(PhoneProvider)
        result = sve.process_result_value(PhoneProvider.VERIZON.value, None)
        assert result == PhoneProvider.VERIZON

    def test_process_result_value_invalid(self) -> None:
        """Test that an invalid value raises ValueError."""
        sve = SqlValueEnum(PhoneProvider)
        with pytest.raises(ValueError, match="Not an"):
            sve.process_result_value(99999, None)

    def test_process_bind_param_none_for_regular_enum(self) -> None:
        """Regular enum with None should return None."""
        sve = SqlValueEnum(PhoneProvider)
        result = sve.process_bind_param(None, None)
        assert result is None

    def test_process_bind_param_valid(self) -> None:
        """Valid enum should return its value."""
        sve = SqlValueEnum(PhoneProvider)
        result = sve.process_bind_param(PhoneProvider.TMOBILE, None)
        assert result == PhoneProvider.TMOBILE.value

    def test_process_result_value_none_returns_none(self) -> None:
        """process_result_value now correctly handles None for nullable columns."""
        sve = SqlValueEnum(PhoneProvider)
        result = sve.process_result_value(None, None)
        assert result is None, "None value should return None for nullable columns"

    def test_none_slips_through_intflag_guard(self) -> None:
        """After fix, passing None for an IntFlag enum raises ValueError."""
        sve = SqlValueEnum(AccountClaims)
        with pytest.raises(ValueError):
            sve.process_bind_param(None, None)


class TestClassproperty:
    """Verify the :class:`~models.internal.classproperty` descriptor."""

    def test_classproperty_basic(self) -> None:
        """Verify :class:`classproperty` can be accessed on the class itself."""

        class Foo:
            """Dummy class for ``classproperty`` testing."""

            @classproperty
            def bar(cls) -> object:
                """Return a constant class-level value."""
                return 42

        assert Foo.bar == 42


class TestFrozenTimestampDefaults:
    """
    datetime.now(UTC) as an insert_default= is evaluated per-insert.
    Two records created at different times get distinct timestamps.
    """

    def test_receipt_default_timestamp_is_frozen(self, db_session: Session) -> None:
        """Verify receipt timestamps are frozen at creation time.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        a1 = create_account("ft_a", "ft_a@t.com", ExternalAuthProvider.test, "ft_a")
        a2 = create_account("ft_b", "ft_b@t.com", ExternalAuthProvider.test, "ft_b")
        db_session.add_all([a1, a2])
        db_session.commit()

        r1 = Receipt(Credits=1, PayerId=a1.id, RecipientId=a2.id)
        db_session.add(r1)
        db_session.commit()

        time.sleep(0.05)

        r2 = Receipt(Credits=2, PayerId=a2.id, RecipientId=a1.id)
        db_session.add(r2)
        db_session.commit()

        assert r1.Time != r2.Time, (
            "Each receipt should get a unique timestamp from insert_default"
        )

    def test_event_default_timestamp_is_frozen(self, db_session: Session) -> None:
        """Verify event timestamps are frozen at creation time.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        from models.happyhour.event import Event

        loc = _make_location(db_session)
        a = create_account("ft_c", "ft_c@t.com", ExternalAuthProvider.test, "ft_c")
        db_session.add(a)
        db_session.commit()

        e1 = Event(LocationID=loc.id, TyrantID=a.id, week_of="2026-W01")
        db_session.add(e1)
        db_session.commit()

        time.sleep(0.05)

        e2 = Event(LocationID=loc.id, TyrantID=a.id, week_of="2026-W02")
        db_session.add(e2)
        db_session.commit()

        assert e1.When != e2.When, (
            "Each event should get a unique timestamp from insert_default"
        )

    def test_rotation_defaults_are_frozen(self, db_session: Session) -> None:
        """Verify rotation assignment timestamps are frozen at creation time.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        from models.happyhour.rotation import TyrantRotation

        a = create_account("ft_d", "ft_d@t.com", ExternalAuthProvider.test, "ft_d")
        db_session.add(a)
        db_session.commit()

        r1 = TyrantRotation(account_id=a.id, cycle=1)
        db_session.add(r1)
        db_session.commit()

        time.sleep(0.05)

        r2 = TyrantRotation(account_id=a.id, cycle=1)
        db_session.add(r2)
        db_session.commit()

        assert r1.assigned_at != r2.assigned_at, (
            "Each rotation should get a unique timestamp from insert_default"
        )


def _make_location(
    s: Session, name: str = "Internal Bar", **overrides: Any
) -> Location:
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
        URL="https://internalbar.com",
        AddressRaw="123 Internal St",
        Number=123,
        StreetName="Internal St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    return create_location(s, **defaults)
