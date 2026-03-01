"""Tests for mealbot database operations."""
import pytest
from datetime import datetime, UTC, timedelta

from db.functions import (
    create_account,
    create_receipt,
    get_all_records,
    get_records_with_limit,
    get_records_for_user,
    get_records_between_users,
    get_timebound_records,
    get_timebound_records_for_user,
    get_global_summary,
    get_summary_for_user,
)
from sqlalchemy.orm import Session
from models import ExternalAuthProvider


def _make_users(s: Session, names: list[str]) -> None:
    """Helper to create multiple test users.

    :param s: Active SQLAlchemy session.
    :type s: Session
    :param names: Usernames to create.
    :type names: list[str]
    """
    for name in names:
        act = create_account(name, f"{name}@test.com", ExternalAuthProvider.test, name)
        s.add(act)
    s.commit()


class TestCreateReceipt:
    """Verify receipt creation and validation."""
    def test_create_receipt(self, db_session: Session) -> None:
        """Verify a receipt is created with the correct credit amount.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["payer", "recip"])
        receipt = create_receipt(db_session, "payer", "recip", 5)
        assert receipt.id is not None
        assert receipt.Credits == 5
        assert receipt.Time is not None

    def test_create_receipt_nonexistent_payer(self, db_session: Session) -> None:
        """Verify a :class:`ValueError` for an unknown payer.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["exists"])
        with pytest.raises(ValueError, match="Payer"):
            create_receipt(db_session, "ghost", "exists", 1)

    def test_create_receipt_nonexistent_recipient(self, db_session: Session) -> None:
        """Verify a :class:`ValueError` for an unknown recipient.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["exists"])
        with pytest.raises(ValueError, match="Recipient"):
            create_receipt(db_session, "exists", "ghost", 1)


class TestGetRecords:
    """Verify record retrieval and filtering."""
    def test_get_all_records(self, db_session: Session) -> None:
        """Verify all records are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["reca", "recb"])
        create_receipt(db_session, "reca", "recb", 3)
        create_receipt(db_session, "recb", "reca", 2)

        records = get_all_records(db_session)
        assert len(records) == 2

    def test_get_records_with_limit(self, db_session: Session) -> None:
        """Verify the *limit* parameter caps the result set.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["lima", "limb"])
        for i in range(5):
            create_receipt(db_session, "lima", "limb", i + 1)

        records = get_records_with_limit(db_session, 3)
        assert len(records) == 3

    def test_get_records_for_user(self, db_session: Session) -> None:
        """Verify records involving a specific user are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["usra", "usrb", "usrc"])
        create_receipt(db_session, "usra", "usrb", 1)
        create_receipt(db_session, "usrc", "usra", 2)
        create_receipt(db_session, "usrb", "usrc", 3)

        records = get_records_for_user(db_session, "usra")
        assert len(records) == 2

    def test_get_records_for_nonexistent_user(self, db_session: Session) -> None:
        """Verify a :class:`ValueError` for an unknown user.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        with pytest.raises(ValueError, match="does not exist"):
            get_records_for_user(db_session, "nobody")

    def test_get_records_between_users(self, db_session: Session) -> None:
        """Verify records between two specific users are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["btwna", "btwnb", "btwnc"])
        create_receipt(db_session, "btwna", "btwnb", 1)
        create_receipt(db_session, "btwnb", "btwna", 2)
        create_receipt(db_session, "btwna", "btwnc", 3)

        records = get_records_between_users(db_session, "btwna", "btwnb")
        assert len(records) == 2


class TestTimeboundRecords:
    """Verify time-bounded record queries."""
    def test_get_timebound_records(self, db_session: Session) -> None:
        """Verify records within a time window are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tba", "tbb"])
        create_receipt(db_session, "tba", "tbb", 1)

        now = datetime.now(UTC)
        records = get_timebound_records(
            db_session,
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
        )
        assert len(records) == 1

    def test_get_timebound_records_outside_range(self, db_session: Session) -> None:
        """Verify records outside the window are excluded.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["outa", "outb"])
        create_receipt(db_session, "outa", "outb", 1)

        far_past = datetime(2000, 1, 1, tzinfo=UTC)
        records = get_timebound_records(
            db_session,
            start=far_past,
            end=far_past + timedelta(hours=1),
        )
        assert len(records) == 0

    def test_get_timebound_records_for_user(self, db_session: Session) -> None:
        """Verify time-bounded records for a specific user.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tbua", "tbub"])
        create_receipt(db_session, "tbua", "tbub", 1)

        now = datetime.now(UTC)
        records = get_timebound_records_for_user(
            db_session, "tbua",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
        )
        assert len(records) == 1


class TestSummary:
    """Verify credit summary aggregation."""
    def test_global_summary(self, db_session: Session) -> None:
        """Verify the global summary includes bidirectional credits.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["suma", "sumb"])
        create_receipt(db_session, "suma", "sumb", 3)
        create_receipt(db_session, "sumb", "suma", 1)

        summary = get_global_summary(db_session)
        assert "suma" in summary
        assert "sumb" in summary
        assert summary["suma"]["sumb"]["outgoing-credits"] == 3
        assert summary["suma"]["sumb"]["incoming-credits"] == 1
        assert summary["sumb"]["suma"]["outgoing-credits"] == 1
        assert summary["sumb"]["suma"]["incoming-credits"] == 3

    def test_summary_for_user(self, db_session: Session) -> None:
        """Verify the per-user summary shows outgoing and incoming credits.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["usuma", "usumb"])
        create_receipt(db_session, "usuma", "usumb", 5)

        summary = get_summary_for_user(db_session, "usuma")
        assert "usumb" in summary
        assert summary["usumb"]["outgoing-credits"] == 5
        assert summary["usumb"]["incoming-credits"] == 0

    def test_summary_for_nonexistent_user(self, db_session: Session) -> None:
        """Verify a :class:`ValueError` for an unknown user.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        with pytest.raises(ValueError, match="does not exist"):
            get_summary_for_user(db_session, "invalid_user")

    def test_timebound_summary_for_user(self, db_session: Session) -> None:
        """Verify the time-bounded per-user summary.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["tsua", "tsub"])
        create_receipt(db_session, "tsua", "tsub", 7)

        now = datetime.now(UTC)
        summary = get_summary_for_user(
            db_session, "tsua",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
        )
        assert summary["tsub"]["outgoing-credits"] == 7
