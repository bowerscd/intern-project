"""Database connection management and session factory."""

from typing import Any

from contextlib import AbstractContextManager
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker, Session

from threading import Lock

from models.database import Model


def _run_alembic_upgrade(engine: Any) -> None:
    """Apply pending Alembic migrations against *engine*.

    Used in production (non-SQLite) so that schema changes always go
    through version-controlled migration scripts rather than
    ``create_all``.

    :param engine: A started :class:`~sqlalchemy.engine.Engine`.
    """
    import logging
    from pathlib import Path

    _logger = logging.getLogger(__name__)

    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command

        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not ini_path.is_file():
            _logger.warning("alembic.ini not found — falling back to create_all")
            Model.metadata.create_all(engine)
            return

        cfg = AlembicConfig(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        alembic_command.upgrade(cfg, "head")
        _logger.info("Alembic migrations applied successfully")
    except Exception:
        _logger.exception("Alembic upgrade failed — falling back to create_all")
        Model.metadata.create_all(engine)
        _stamp_if_unversioned(engine)


def _stamp_if_unversioned(engine: Any) -> None:
    """Stamp the Alembic version table when the schema already exists.

    On the very first run after adding Alembic to an existing database,
    the tables will already be present but there will be no
    ``alembic_version`` row.  This function detects that situation and
    stamps the database at ``head`` so future ``alembic upgrade`` runs
    work correctly.

    Does nothing if Alembic is not installed, or if the database is
    already stamped, or if the database has no tables yet (fresh).

    :param engine: A started :class:`~sqlalchemy.engine.Engine`.
    """
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        from pathlib import Path
        import logging

        _logger = logging.getLogger(__name__)

        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not ini_path.is_file():
            return

        inspector = sa_inspect(engine)
        table_names = inspector.get_table_names()

        # No existing tables → fresh DB, nothing to stamp
        if not table_names:
            return

        # Already stamped → nothing to do
        if "alembic_version" in table_names:
            return

        _logger.info("Stamping existing database at Alembic 'head'")
        cfg = AlembicConfig(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        alembic_command.stamp(cfg, "head")
    except Exception:
        import logging

        logging.getLogger(__name__).debug("Alembic stamp skipped", exc_info=True)


class Database(AbstractContextManager[Any]):
    """Thread-safe singleton database manager.

    Wraps a SQLAlchemy engine and session-maker with reference-counted
    start/stop semantics and a context-manager interface.
    """

    _instance: "Database"

    def __new__(
        cls, uri: str | None = None, filename: str | None = None, **kwargs: Any
    ) -> "Database":
        """Ensure only one :class:`Database` instance exists (singleton).

        :param uri: SQLAlchemy connection URI, or ``None`` for in-memory.
        :param filename: SQLite file path (used only when *uri* is set).
        :param kwargs: Extra ``connect_args`` forwarded to
            :func:`create_engine`.
        :returns: The singleton database instance.
        :rtype: Database
        """

        if not hasattr(cls, "_instance"):
            cls._instance = super(Database, cls).__new__(cls)

        return cls._instance

    def __init__(
        self, uri: str | None = None, filename: str | None = None, **kwargs: Any
    ) -> None:
        """Initialise connection parameters (runs only on first creation).

        When *uri* is ``None``, the value from :pydata:`config.DATABASE_URI`
        is tried before falling back to an ephemeral in-memory database.

        :param uri: SQLAlchemy connection URI.
        :param filename: SQLite file path.
        :param kwargs: Extra ``connect_args`` forwarded to
            :func:`create_engine`.
        """
        if hasattr(self, "_started"):
            return

        from random import randint
        from config import DATABASE_URI

        self._started_lock = Lock()
        self._ref_count = 0
        self._started = False
        self._engine = None
        self._sessionmaker = None

        if uri is None and DATABASE_URI is not None:
            uri = DATABASE_URI

        if uri is not None:
            if filename is not None:
                self._cnx_uri = f"sqlite:///{filename}"
            else:
                self._cnx_uri = uri
        else:
            self._cnx_uri = f"sqlite:///file:{''.join([chr(randint(ord('a'), ord('z'))) for _ in range(0, 8)])}?mode=memory&cache=shared&uri=true"

        if kwargs:
            self._cnx_args = kwargs
        elif self._cnx_uri.startswith("sqlite"):
            self._cnx_args = {"check_same_thread": False}
        else:
            self._cnx_args = {}

    def start(self) -> None:
        """Start the database engine and create all tables.

        Safe to call multiple times — uses reference counting.
        """
        with self._started_lock:
            self._start_locked()

    def _start_locked(self) -> None:
        """Start the database engine (must be called while holding ``_started_lock``).

        Increments the reference count and, on the first call, creates
        the engine and session-maker.  For non-SQLite databases the schema
        is applied via ``alembic upgrade head`` so that migrations are
        respected.  SQLite (dev/test) falls back to ``create_all``.
        """
        self._ref_count += 1

        if self._started:
            return

        pool_kwargs: dict = {}
        if not self._cnx_uri.startswith("sqlite"):
            pool_kwargs = {
                "pool_pre_ping": True,
                "pool_recycle": 1800,
            }

        self._engine = create_engine(
            self._cnx_uri, echo=False, connect_args=self._cnx_args, **pool_kwargs
        )

        self._sessionmaker = sessionmaker(self._engine)

        if self._cnx_uri.startswith("sqlite"):
            # Dev/test: create tables directly (ephemeral databases)
            Model.metadata.create_all(self._engine)
            _stamp_if_unversioned(self._engine)
        else:
            # Production: apply schema through Alembic migrations
            _run_alembic_upgrade(self._engine)

        self._started = True

    def stop(self) -> None:
        """Stop the database engine when the last reference is released.

        Does nothing if the ref-count is already zero.

        :raises Exception: If the engine was never initialised.
        """
        from sqlalchemy.orm.session import close_all_sessions

        if self._engine is None:
            raise Exception("something has gone terribly, terribly, wrong")

        with self._started_lock:
            if self._ref_count <= 0:
                return

            self._ref_count -= 1

            if self._ref_count == 0:
                self._engine.dispose()
                close_all_sessions()
                self._sessionmaker = None
                self._started = False

    def session(self) -> Session:
        """Create and return a new database session.

        Automatically starts the engine if it has not been started.
        Access to the session-maker is guarded by the start lock.

        :returns: A new SQLAlchemy :class:`Session`.
        :rtype: Session
        """
        with self._started_lock:
            if self._sessionmaker is None:
                self._start_locked()

            s = self._sessionmaker()
        return s

    def __enter__(self) -> "Database":
        """Start the database and return this instance.

        :returns: The database manager.
        :rtype: Database
        """
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        """Stop the database on context-manager exit."""
        self.stop()
