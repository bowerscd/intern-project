"""Tests for Database session lifecycle, singleton behavior, and session cleanup."""

from random import randint
from threading import Lock

from db import Database


class TestDatabaseSingleton:
    """
    Database.__new__ returns the cached instance regardless of arguments.
    Database.__init__ returns early if _started already exists.
    """

    def test_singleton_returns_same_instance(self) -> None:
        """Two Database() calls return the same object."""
        db1 = Database()
        db2 = Database("sqlite:///different.db")
        assert db1 is db2, "Singleton returns same instance regardless of URI"


class TestDatabaseStopDoesNotResetSessionmaker:
    """After stop(), _sessionmaker is now properly reset to None,
    allowing session() to auto-restart the engine."""

    def test_sessionmaker_reset_after_stop(self) -> None:
        """Verify ``_sessionmaker`` is ``None`` after :meth:`Database.stop`."""
        db = Database.__new__(Database)
        db._started_lock = Lock()
        db._cnx_uri = f"sqlite:///file:{''.join([chr(randint(ord('a'), ord('z'))) for _ in range(0, 8)])}?mode=memory&cache=shared&uri=true"
        db._cnx_args = {"check_same_thread": False}

        db.start()
        assert db._sessionmaker is not None
        assert db._started is True

        db.stop()
        assert db._started is False

        # FIXED: _sessionmaker is now reset after stop, so session() will auto-restart
        assert db._sessionmaker is None, (
            "_sessionmaker should be reset to None after stop()"
        )
