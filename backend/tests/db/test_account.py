"""Tests for account database operations."""

import pytest

from db.functions import (
    create_account,
    get_account_by_email,
    get_account_by_phone,
    get_account_by_username,
    get_account_by_id,
    get_account_by_provider,
    get_all_accounts,
    get_accounts_with_claim,
)
from sqlalchemy.orm import Session
from models import ExternalAuthProvider, PhoneProvider, AccountClaims


class TestCreateAccount:
    """Verify account creation and uniqueness constraints."""

    def test_create_account_basic(self, db_session: Session) -> None:
        """Verify basic account creation stores username and email.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account("alice", "alice@test.com", ExternalAuthProvider.test, "a1")
        db_session.add(act)
        db_session.commit()

        assert act.id is not None
        assert act.username == "alice"
        assert act.email == "alice@test.com"
        assert act.claims == AccountClaims.NONE

    def test_create_account_with_claims(self, db_session: Session) -> None:
        """Verify claims are persisted on account creation.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "bob",
            "bob@test.com",
            ExternalAuthProvider.test,
            "b1",
            claims=AccountClaims.MEALBOT | AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        assert act.claims & AccountClaims.MEALBOT == AccountClaims.MEALBOT
        assert act.claims & AccountClaims.HAPPY_HOUR == AccountClaims.HAPPY_HOUR
        assert act.claims & AccountClaims.ADMIN != AccountClaims.ADMIN

    def test_create_account_with_phone(self, db_session: Session) -> None:
        """Verify phone number and provider are stored correctly.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "carol",
            "carol@test.com",
            ExternalAuthProvider.test,
            "c1",
            phone="5551234567",
            phone_provider=PhoneProvider.VERIZON,
        )
        db_session.add(act)
        db_session.commit()

        assert act.phone == "5551234567"
        assert act.phone_provider == PhoneProvider.VERIZON

    def test_duplicate_username_raises(self, db_session: Session) -> None:
        """Verify duplicate usernames raise :class:`IntegrityError`.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act1 = create_account(
            "dupeuser", "dup1@test.com", ExternalAuthProvider.test, "d1"
        )
        db_session.add(act1)
        db_session.commit()

        act2 = create_account(
            "dupeuser", "dup2@test.com", ExternalAuthProvider.test, "d2"
        )
        db_session.add(act2)
        with pytest.raises(Exception):
            db_session.commit()

    def test_duplicate_email_raises(self, db_session: Session) -> None:
        """Verify duplicate emails raise :class:`IntegrityError`.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act1 = create_account(
            "email1", "same@test.com", ExternalAuthProvider.test, "e1"
        )
        db_session.add(act1)
        db_session.commit()

        act2 = create_account(
            "email2", "same@test.com", ExternalAuthProvider.test, "e2"
        )
        db_session.add(act2)
        with pytest.raises(Exception):
            db_session.commit()


class TestGetAccount:
    """Verify account retrieval by various lookup keys."""

    def test_get_by_email(self, db_session: Session) -> None:
        """Verify account lookup by email address.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "byemail", "find@test.com", ExternalAuthProvider.test, "f1"
        )
        db_session.add(act)
        db_session.commit()

        found = get_account_by_email(db_session, "find@test.com")
        assert found is not None
        assert found.username == "byemail"

    def test_get_by_email_not_found(self, db_session: Session) -> None:
        """Verify ``None`` is returned for an unknown email.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        result = get_account_by_email(db_session, "nonexistent@none.com")
        assert result is None

    def test_get_by_phone(self, db_session: Session) -> None:
        """Verify account lookup by phone number.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "byphone",
            "phone@test.com",
            ExternalAuthProvider.test,
            "ph1",
            phone="5559999999",
            phone_provider=PhoneProvider.TMOBILE,
        )
        db_session.add(act)
        db_session.commit()

        found = get_account_by_phone(db_session, "5559999999")
        assert found is not None
        assert found.username == "byphone"

    def test_get_by_username(self, db_session: Session) -> None:
        """Verify account lookup by username.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account("findme", "fm@test.com", ExternalAuthProvider.test, "fm1")
        db_session.add(act)
        db_session.commit()

        found = get_account_by_username(db_session, "findme")
        assert found is not None
        assert found.email == "fm@test.com"

    def test_get_by_username_not_found(self, db_session: Session) -> None:
        """Verify ``None`` is returned for an unknown username.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        assert get_account_by_username(db_session, "nobody_here") is None

    def test_get_by_id(self, db_session: Session) -> None:
        """Verify account lookup by primary key.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account("byid", "byid@test.com", ExternalAuthProvider.test, "id1")
        db_session.add(act)
        db_session.commit()

        found = get_account_by_id(db_session, act.id)
        assert found is not None
        assert found.username == "byid"

    def test_get_by_provider(self, db_session: Session) -> None:
        """Verify account lookup by external auth provider and ID.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "byprov", "prov@test.com", ExternalAuthProvider.google, "goog-123"
        )
        db_session.add(act)
        db_session.commit()

        found = get_account_by_provider(
            db_session, ExternalAuthProvider.google, "goog-123"
        )
        assert found is not None
        assert found.username == "byprov"

    def test_get_by_provider_not_found(self, db_session: Session) -> None:
        """Verify ``None`` is returned for an unknown provider ID.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        assert (
            get_account_by_provider(db_session, ExternalAuthProvider.google, "nope")
            is None
        )

    def test_get_all_accounts(self, db_session: Session) -> None:
        """Verify all persisted accounts are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        for i in range(3):
            act = create_account(
                f"all{i}", f"all{i}@test.com", ExternalAuthProvider.test, f"all{i}"
            )
            db_session.add(act)
        db_session.commit()

        accounts = get_all_accounts(db_session)
        assert len(accounts) >= 3


class TestAccountClaims:
    """Verify bitwise claim-flag queries."""

    def test_get_accounts_with_claim(self, db_session: Session) -> None:
        """Verify only accounts matching the requested claim are returned.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        a1 = create_account(
            "clm1",
            "clm1@test.com",
            ExternalAuthProvider.test,
            "cl1",
            claims=AccountClaims.MEALBOT,
        )
        a2 = create_account(
            "clm2",
            "clm2@test.com",
            ExternalAuthProvider.test,
            "cl2",
            claims=AccountClaims.HAPPY_HOUR,
        )
        a3 = create_account(
            "clm3",
            "clm3@test.com",
            ExternalAuthProvider.test,
            "cl3",
            claims=AccountClaims.MEALBOT | AccountClaims.HAPPY_HOUR,
        )
        db_session.add_all([a1, a2, a3])
        db_session.commit()

        mealbot_users = get_accounts_with_claim(db_session, AccountClaims.MEALBOT)
        usernames = [u.username for u in mealbot_users]
        assert "clm1" in usernames
        assert "clm3" in usernames
        assert "clm2" not in usernames
