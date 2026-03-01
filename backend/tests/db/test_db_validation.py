"""
Tests for db/functions validation:
- resolve_summary ignores time filters for global summary
- create_receipt allows self-payments (payer == recipient)
- Scheduler partial commits — no atomicity across operations
"""

import pytest
from datetime import datetime, UTC

from db.functions import (
    create_account,
    create_receipt,
    get_records_for_user,
    get_global_summary,
    create_location,
    create_tyrant_assignment,
    mark_assignment_missed,
)
from typing import Any
from models.happyhour.location import Location
from sqlalchemy.orm import Session
from models import ExternalAuthProvider, AccountClaims
from models.enums import TyrantAssignmentStatus
from models.happyhour.rotation import TyrantRotation


def _make_users(s: Session, names: list[str]) -> object:
    """Create one or more test user accounts.

    :param s: Active database session.
    :type s: Session
    :param names: Usernames to create.
    :type names: list[str]
    """
    accounts = []
    for name in names:
        act = create_account(name, f"{name}@test.com", ExternalAuthProvider.test, name)
        s.add(act)
        accounts.append(act)
    s.commit()
    return accounts


def _make_location(
    s: Session, name: str = "DB Finding Bar", **overrides: Any
) -> Location:
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
        URL="https://dbfindingbar.com",
        AddressRaw="789 DB St",
        Number=789,
        StreetName="DB St",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    return create_location(s, **defaults)


class TestGlobalSummaryIgnoresTimeFilters:
    """
    resolve_summary calls get_global_summary(db) when user=None,
    which takes no time parameters. Time filters (start, end) are silently ignored
    for global summaries. There is no get_timebound_global_summary function.
    """

    def test_resolve_summary_ignores_time_when_no_user(
        self, db_session: Session
    ) -> None:
        """resolve_summary with user=None ignores start/end parameters.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        a1, a2 = _make_users(db_session, ["gst1", "gst2"])

        # Create receipt at current time
        create_receipt(db_session, "gst1", "gst2", 5)

        # Create an old receipt manually
        from models import DBReceipt as Receipt

        old_receipt = Receipt(
            Credits=10,
            Time=datetime(2020, 1, 1, tzinfo=UTC),
            PayerId=a1.id,
            RecipientId=a2.id,
        )
        db_session.add(old_receipt)
        db_session.commit()

        from routes.shared import resolve_summary

        # Request only 2025 data — should exclude the 2020 receipt
        result = resolve_summary(
            db_session,
            None,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 12, 31, tzinfo=UTC),
        )

        # result is {gst1: {gst2: {outgoing-credits: N, incoming-credits: N}}, ...}
        total_out = result["gst1"]["gst2"]["outgoing-credits"]
        # If time filters worked, total should be 5 (just the current receipt)
        # But they are ignored for global summary, so total is 15 (5 + 10)
        assert total_out == 15, (
            f"Global summary ignores time filters, "
            f"got {total_out} (expected 15 if all-time, 5 if filtered)"
        )


class TestSelfPayment:
    """
    create_receipt validates that payer != recipient.
    Self-payments are rejected with ValueError.
    """

    def test_self_payment_is_rejected(self, db_session: Session) -> None:
        """create_receipt raises ValueError when payer == recipient.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["selfpay"])
        with pytest.raises(ValueError, match="same person"):
            create_receipt(db_session, "selfpay", "selfpay", 5)

    def test_self_payment_does_not_appear_in_records(self, db_session: Session) -> None:
        """No records are created from a rejected self-payment.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        _make_users(db_session, ["selfpay2"])
        with pytest.raises(ValueError):
            create_receipt(db_session, "selfpay2", "selfpay2", 3)
        records = get_records_for_user(db_session, "selfpay2")
        assert len(records) == 0, "No records should exist for rejected self-payment"

    def test_mixed_self_and_real_payments(self, db_session: Session) -> None:
        """
        A self-payment raises ValueError; a subsequent real payment works.
        The ledger only contains the real payment.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        a1, a2 = _make_users(db_session, ["sp_alice", "sp_bob"])
        with pytest.raises(ValueError):
            create_receipt(db_session, "sp_alice", "sp_alice", 5)
        create_receipt(db_session, "sp_alice", "sp_bob", 3)

        records = get_records_for_user(db_session, "sp_alice")
        assert len(records) == 1, "Only the real payment should exist"

        summary = get_global_summary(db_session)
        total_out = summary["sp_alice"]["sp_bob"]["outgoing-credits"]
        assert total_out == 3, "Summary shows only the real payment"


class TestSchedulerAtomicity:
    """
    auto_select_happy_hour performs multiple independent
    commits (mark_assignment_missed, remove_claim, create_event).
    If a later operation fails, earlier commits are permanent.
    """

    def test_mark_missed_commits_independently(self, db_session: Session) -> None:
        """mark_assignment_missed commits to the DB immediately.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        a = create_account(
            "atom1",
            "atom1@t.com",
            ExternalAuthProvider.test,
            "atom1",
            claims=AccountClaims.BASIC | AccountClaims.HAPPY_HOUR_TYRANT,
        )
        db_session.add(a)
        db_session.commit()

        assignment = create_tyrant_assignment(
            db_session,
            a.id,
            1,
            position=0,
            assigned_at=datetime.now(UTC),
            deadline_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.PENDING,
        )
        assert assignment.status == TyrantAssignmentStatus.PENDING

        # This commits immediately
        mark_assignment_missed(db_session, assignment.id)

        # Refresh to verify it's persisted
        db_session.expire_all()
        refreshed = db_session.get(TyrantRotation, assignment.id)
        assert refreshed.status == TyrantAssignmentStatus.MISSED, (
            "mark_assignment_missed committed independently — "
            "if create_event fails after this, state is inconsistent"
        )
