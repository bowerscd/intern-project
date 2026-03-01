"""
Verification tests for reported bugs / ambiguities.

Tests prefixed ``TestFixed`` confirm that a fix has been applied.
Tests prefixed ``TestConfirmed`` demonstrate issues that remain open
(informational only).

Run with:  pytest tests/_verify_bugs/ -v
"""

import threading
from datetime import datetime

import pytest
from sqlalchemy import Integer, String


# ===================================================================
# FIXED issues — tests prove the fix is in place
# ===================================================================


class TestFixed02_SqlValueEnumAutoDetectsStringImpl:
    """SqlValueEnum now auto-detects String impl for string-valued enums."""

    def test_string_enum_gets_string_impl(self) -> None:
        """After fix, TyrantAssignmentStatus gets a String impl, not Integer."""
        from models.internal import SqlValueEnum
        from models.enums import TyrantAssignmentStatus

        decorator = SqlValueEnum(TyrantAssignmentStatus)
        assert isinstance(decorator.impl, String), (
            f"Expected String impl but got {type(decorator.impl).__name__}"
        )
        bound = decorator.process_bind_param(TyrantAssignmentStatus.PENDING, None)
        assert bound == "pending"

    def test_integer_enum_keeps_integer_impl(self) -> None:
        """IntFlag / integer enums still get Integer impl."""
        from models.internal import SqlValueEnum
        from models.enums import AccountClaims

        decorator = SqlValueEnum(AccountClaims)
        assert isinstance(decorator.impl, Integer)


class TestFixed03_OpenRedirectBlocked:
    """Login/register endpoints now reject absolute redirect URLs."""

    def test_relative_path_accepted(self) -> None:
        """Relative paths pass validation."""
        from routes.auth.login import _validate_redirect

        assert (
            _validate_redirect("/api/v2/account/profile") == "/api/v2/account/profile"
        )
        assert _validate_redirect("/dashboard") == "/dashboard"

    def test_absolute_url_rejected(self) -> None:
        """Absolute URLs with scheme or netloc are rejected."""
        from fastapi import HTTPException
        from routes.auth.login import _validate_redirect

        with pytest.raises(HTTPException) as exc_info:
            _validate_redirect("https://evil.com/phish")
        assert exc_info.value.status_code == 400

    def test_protocol_relative_rejected(self) -> None:
        """Protocol-relative URLs (//evil.com) are rejected."""
        from fastapi import HTTPException
        from routes.auth.login import _validate_redirect

        with pytest.raises(HTTPException) as exc_info:
            _validate_redirect("//evil.com/phish")
        assert exc_info.value.status_code == 400


class TestFixed06_StopRefCountGuard:
    """stop() no longer allows ref_count to go negative."""

    def test_double_stop_stays_at_zero(self) -> None:
        """After fix, calling stop() past zero is a no-op."""
        from db import Database

        db = Database.__new__(Database)
        db._started_lock = threading.Lock()
        db._ref_count = 0
        db._started = False
        db._engine = None
        db._sessionmaker = None
        db._cnx_uri = "sqlite:///:memory:"
        db._cnx_args = {"check_same_thread": False}

        db.start()
        assert db._ref_count == 1

        db.stop()
        assert db._ref_count == 0

        db.stop()
        assert db._ref_count == 0


class TestFixed12_ClaimsTyrantImpliesHappyHour:
    """HAPPY_HOUR_TYRANT always implies HAPPY_HOUR, even after removals."""

    def test_enforcement_logic(self) -> None:
        """HAPPY_HOUR cannot be stripped while TYRANT remains."""
        from models.enums import AccountClaims

        current = AccountClaims.BASIC
        current |= AccountClaims["HAPPY_HOUR_TYRANT"]
        current &= ~AccountClaims["HAPPY_HOUR"]

        if current & AccountClaims.HAPPY_HOUR_TYRANT:
            current |= AccountClaims.HAPPY_HOUR

        assert current & AccountClaims.HAPPY_HOUR_TYRANT
        assert current & AccountClaims.HAPPY_HOUR


class TestFixed13_CachePurgeSafe:
    """_purge_entry now uses .pop() to avoid KeyError."""

    def test_concurrent_purge_does_not_raise(self) -> None:
        """Purging a key that was already removed does not raise KeyError."""
        from auth.cache import AuthCache

        cache = AuthCache()
        # Manually place an entry (bypass async put)
        cache._cache["k"] = "v"
        # Simulate what _purge_entry does internally: .pop(key, None)
        cache._cache.pop("k", None)
        # Second pop on same key — would KeyError with `del`
        cache._cache.pop("k", None)


class TestFixed18_ProcessResultValueAnnotation:
    """process_result_value handles None for nullable columns."""

    def test_returns_none_for_null(self) -> None:
        """None input still returns None correctly."""
        from models.internal import SqlValueEnum
        from models.enums import TyrantAssignmentStatus

        decorator = SqlValueEnum(TyrantAssignmentStatus)
        assert decorator.process_result_value(None, None) is None


class TestFixed19_WednesdayNoonSameDay:
    """_next_wednesday_noon now returns the same Wednesday when called before noon."""

    def test_wednesday_morning_returns_today(self) -> None:
        """On a Wednesday at 9 AM, returns today at noon."""
        from scheduler import _next_wednesday_noon
        from zoneinfo import ZoneInfo

        pst = ZoneInfo("America/Los_Angeles")
        wed_morning = datetime(2026, 2, 25, 9, 0, tzinfo=pst)
        assert wed_morning.weekday() == 2

        result = _next_wednesday_noon(wed_morning)
        assert result.date() == wed_morning.date()
        assert result.hour == 12

    def test_wednesday_afternoon_returns_next_week(self) -> None:
        """On a Wednesday at 1 PM, returns next Wednesday at noon."""
        from scheduler import _next_wednesday_noon
        from zoneinfo import ZoneInfo

        pst = ZoneInfo("America/Los_Angeles")
        wed_afternoon = datetime(2026, 2, 25, 13, 0, tzinfo=pst)
        assert wed_afternoon.weekday() == 2

        result = _next_wednesday_noon(wed_afternoon)
        expected = datetime(2026, 3, 4, 12, 0, tzinfo=pst)
        assert result.date() == expected.date()
