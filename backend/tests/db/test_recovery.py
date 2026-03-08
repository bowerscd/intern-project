"""Tests for disaster recovery DB functions — event/receipt/rotation operations."""

from datetime import datetime, UTC, timedelta

from sqlalchemy.orm import Session

from db.functions import (
    create_account,
    create_event,
    create_location,
    create_receipt,
    delete_event,
    delete_receipt,
    get_consecutive_misses,
    get_event_by_id,
    get_receipt_by_id,
    skip_assignment,
    update_event_fields,
    create_tyrant_assignment,
)
from models import (
    AccountClaims,
    AccountStatus,
    ExternalAuthProvider,
    TyrantAssignmentStatus,
)


def _mk_account(s: Session, username: str = "recovery_test") -> int:
    act = create_account(
        username,
        f"{username}@test.com",
        ExternalAuthProvider.test,
        username,
        claims=AccountClaims.MEALBOT
        | AccountClaims.HAPPY_HOUR
        | AccountClaims.HAPPY_HOUR_TYRANT,
    )
    act.status = AccountStatus.ACTIVE
    s.add(act)
    s.flush()
    return act.id


def _mk_location(s: Session) -> int:
    loc = create_location(
        s,
        Name="Recovery Tavern",
        URL="https://recovery.test",
        AddressRaw="999 Recovery St, Portland, OR 97201",
        Number=999,
        StreetName="Recovery St",
        City="Portland",
        State="OR",
        ZipCode="97201",
        Latitude=45.52,
        Longitude=-122.68,
    )
    return loc.id


class TestDeleteEvent:
    """Test delete_event DB function."""

    def test_delete_existing_event(self, db_session: Session) -> None:
        _mk_account(db_session)
        loc_id = _mk_location(db_session)
        event = create_event(
            db_session,
            location_id=loc_id,
            when=datetime.now(UTC) + timedelta(days=3),
        )
        event_id = event.id
        db_session.commit()

        delete_event(db_session, event_id)
        db_session.commit()

        assert get_event_by_id(db_session, event_id) is None

    def test_delete_nonexistent_event_raises(self, db_session: Session) -> None:
        import pytest

        with pytest.raises(ValueError, match="does not exist"):
            delete_event(db_session, 99999)


class TestUpdateEventFields:
    """Test update_event_fields DB function."""

    def test_update_description(self, db_session: Session) -> None:
        _mk_account(db_session)
        loc_id = _mk_location(db_session)
        event = create_event(
            db_session,
            location_id=loc_id,
            when=datetime.now(UTC) + timedelta(days=3),
            description="original",
        )
        db_session.commit()

        updated = update_event_fields(db_session, event.id, description="changed")
        assert updated is not None
        assert updated.Description == "changed"

    def test_update_location(self, db_session: Session) -> None:
        _mk_account(db_session)
        loc1_id = _mk_location(db_session)
        loc2 = create_location(
            db_session,
            Name="Alt Pub",
            URL=None,
            AddressRaw="1 Alt St",
            Number=1,
            StreetName="Alt",
            City="X",
            State="OR",
            ZipCode="00000",
            Latitude=0.0,
            Longitude=0.0,
        )
        event = create_event(
            db_session,
            location_id=loc1_id,
            when=datetime.now(UTC) + timedelta(days=3),
        )
        db_session.commit()

        updated = update_event_fields(db_session, event.id, location_id=loc2.id)
        assert updated is not None
        assert updated.LocationID == loc2.id

    def test_update_nonexistent_returns_none(self, db_session: Session) -> None:
        result = update_event_fields(db_session, 99999, description="x")
        assert result is None


class TestDeleteReceipt:
    """Test delete_receipt DB function."""

    def test_delete_existing_receipt(self, db_session: Session) -> None:
        _mk_account(db_session, "payer1")
        _mk_account(db_session, "recpt1")
        receipt = create_receipt(db_session, "payer1", "recpt1", 3)
        receipt_id = receipt.id
        db_session.commit()

        delete_receipt(db_session, receipt_id)
        db_session.commit()

        assert get_receipt_by_id(db_session, receipt_id) is None

    def test_delete_nonexistent_receipt_raises(self, db_session: Session) -> None:
        import pytest

        with pytest.raises(ValueError, match="does not exist"):
            delete_receipt(db_session, 99999)


class TestGetReceiptById:
    """Test get_receipt_by_id DB function."""

    def test_get_existing_receipt(self, db_session: Session) -> None:
        _mk_account(db_session, "payerx")
        _mk_account(db_session, "recpx")
        receipt = create_receipt(db_session, "payerx", "recpx", 5)
        db_session.commit()

        found = get_receipt_by_id(db_session, receipt.id)
        assert found is not None
        assert found.Credits == 5
        assert found.Payer.username == "payerx"

    def test_get_nonexistent_receipt(self, db_session: Session) -> None:
        assert get_receipt_by_id(db_session, 99999) is None


class TestSkipAssignment:
    """Test skip_assignment and its interaction with consecutive misses."""

    def test_skip_sets_status(self, db_session: Session) -> None:
        act_id = _mk_account(db_session, "skipper")
        assignment = create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=0,
            assigned_at=datetime.now(UTC),
            status=TyrantAssignmentStatus.PENDING,
        )
        db_session.commit()

        skip_assignment(db_session, assignment.id)
        db_session.commit()
        db_session.refresh(assignment)

        assert assignment.status == TyrantAssignmentStatus.SKIPPED

    def test_skipped_does_not_count_as_miss(self, db_session: Session) -> None:
        """SKIPPED assignments should not count toward consecutive misses."""
        act_id = _mk_account(db_session, "misstest")
        now = datetime.now(UTC)

        # Create: MISSED, SKIPPED, MISSED sequence
        create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=0,
            assigned_at=now - timedelta(days=21),
            status=TyrantAssignmentStatus.MISSED,
        )
        create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=1,
            assigned_at=now - timedelta(days=14),
            status=TyrantAssignmentStatus.SKIPPED,
        )
        create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=2,
            assigned_at=now - timedelta(days=7),
            status=TyrantAssignmentStatus.MISSED,
        )
        db_session.commit()

        # Should count 2 consecutive misses (SKIPPED is ignored)
        misses = get_consecutive_misses(db_session, act_id)
        assert misses == 2

    def test_skipped_between_chosen_and_missed(self, db_session: Session) -> None:
        """SKIPPED between a CHOSEN and MISSED should not break the streak."""
        act_id = _mk_account(db_session, "streaktest")
        now = datetime.now(UTC)

        # Create: CHOSEN (oldest), SKIPPED, MISSED (newest)
        create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=0,
            assigned_at=now - timedelta(days=21),
            status=TyrantAssignmentStatus.CHOSEN,
        )
        create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=1,
            assigned_at=now - timedelta(days=14),
            status=TyrantAssignmentStatus.SKIPPED,
        )
        create_tyrant_assignment(
            db_session,
            account_id=act_id,
            cycle=1,
            position=2,
            assigned_at=now - timedelta(days=7),
            status=TyrantAssignmentStatus.MISSED,
        )
        db_session.commit()

        # Should only count 1 miss (SKIPPED is transparent, CHOSEN breaks streak)
        misses = get_consecutive_misses(db_session, act_id)
        assert misses == 1
