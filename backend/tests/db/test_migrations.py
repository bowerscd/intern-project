"""Tests for Alembic migration infrastructure."""
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

_ROOT = Path(__file__).resolve().parent.parent.parent
_INI = _ROOT / "alembic.ini"


def _make_cfg(url: str) -> AlembicConfig:
    """Create an Alembic config pointing at the given database URL.

    :param url: SQLAlchemy connection URI.
    :returns: An :class:`AlembicConfig` ready for use.
    """
    cfg = AlembicConfig(str(_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


class TestMigrationUpgradeDowngrade:
    """Verify the full upgrade → downgrade cycle works."""

    def test_upgrade_creates_all_tables(self, tmp_path: Path) -> None:
        """``upgrade head`` should create every expected table.

        :param tmp_path: Pytest-provided temporary directory.
        """
        db_path = tmp_path / "test.db"
        url = f"sqlite:///{db_path}"
        cfg = _make_cfg(url)

        alembic_command.upgrade(cfg, "head")

        engine = create_engine(url)
        tables = set(sa_inspect(engine).get_table_names())
        engine.dispose()

        expected = {
            "alembic_version",
            "accounts",
            "account_claim_requests",
            "receipts",
            "HappyHourLocations",
            "HappyHourEvents",
            "HappyHourTyrantRotation",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_downgrade_removes_tables(self, tmp_path: Path) -> None:
        """``downgrade base`` should remove all application tables.

        :param tmp_path: Pytest-provided temporary directory.
        """
        db_path = tmp_path / "test.db"
        url = f"sqlite:///{db_path}"
        cfg = _make_cfg(url)

        alembic_command.upgrade(cfg, "head")
        alembic_command.downgrade(cfg, "base")

        engine = create_engine(url)
        tables = set(sa_inspect(engine).get_table_names())
        engine.dispose()

        # Only alembic_version (with no rows) should remain
        app_tables = tables - {"alembic_version"}
        assert app_tables == set(), f"Tables left after downgrade: {app_tables}"


class TestMigrationNoDrift:
    """Ensure autogenerate detects no new operations after upgrade."""

    def test_no_model_drift(self, tmp_path: Path) -> None:
        """After ``upgrade head`` the schema should match the ORM exactly.

        :param tmp_path: Pytest-provided temporary directory.
        """
        db_path = tmp_path / "test.db"
        url = f"sqlite:///{db_path}"
        cfg = _make_cfg(url)

        alembic_command.upgrade(cfg, "head")

        # alembic check exits non-zero on drift — succeeds otherwise
        alembic_command.check(cfg)


class TestStampIfUnversioned:
    """``_stamp_if_unversioned`` stamps existing databases at head."""

    def test_stamp_on_existing_tables(self, tmp_path: Path) -> None:
        """A database with tables but no alembic_version gets stamped.

        :param tmp_path: Pytest-provided temporary directory.
        """
        from models.database import Model
        from db import _stamp_if_unversioned

        db_path = tmp_path / "existing.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)

        # Create tables without alembic
        Model.metadata.create_all(engine)

        tables_before = set(sa_inspect(engine).get_table_names())
        assert "alembic_version" not in tables_before

        _stamp_if_unversioned(engine)

        tables_after = set(sa_inspect(engine).get_table_names())
        assert "alembic_version" in tables_after

        # Verify the stamp is at head
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            assert len(rows) == 1
            assert rows[0][0] is not None

        engine.dispose()

    def test_stamp_skips_empty_database(self, tmp_path: Path) -> None:
        """An empty database should not be stamped.

        :param tmp_path: Pytest-provided temporary directory.
        """
        from db import _stamp_if_unversioned

        db_path = tmp_path / "empty.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)

        _stamp_if_unversioned(engine)

        tables = set(sa_inspect(engine).get_table_names())
        assert "alembic_version" not in tables

        engine.dispose()

    def test_stamp_idempotent(self, tmp_path: Path) -> None:
        """Calling stamp twice should not error.

        :param tmp_path: Pytest-provided temporary directory.
        """
        from models.database import Model
        from db import _stamp_if_unversioned

        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Model.metadata.create_all(engine)

        _stamp_if_unversioned(engine)
        _stamp_if_unversioned(engine)  # second call — should be a no-op

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            assert len(rows) == 1

        engine.dispose()
