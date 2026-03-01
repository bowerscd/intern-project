"""Tests for mail module."""

import pytest
from datetime import datetime, UTC, timedelta
from email.mime.text import MIMEText

from mail import smtp_cfg, smtp_server_mail
from mail.outgoing import send_email, send_sms, notify_happy_hour_users

from db.functions import (
    create_account,
    create_event,
)
from models.happyhour.location import Location
from pytest_localserver.smtp import Server as SMTPServer
from sqlalchemy.orm import Session
from models import ExternalAuthProvider, AccountClaims, PhoneProvider


class TestSmtpConfig:
    """Verify SMTP configuration is read from environment variables."""

    def test_smtp_cfg(self, smtp: SMTPServer) -> None:
        """Verify :func:`smtp_cfg` returns host, port, and credentials.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        cfg = smtp_cfg()
        assert cfg.Hostname is not None
        assert cfg.Port is not None
        assert cfg.Scheme == "smtp"

    def test_smtp_server_mail(self, smtp: SMTPServer) -> None:
        """Verify :func:`smtp_server_mail` returns the sender address.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        sender = smtp_server_mail()
        assert sender == "pytest@localhost"

    def test_smtp_server_mail_with_subtype(self, smtp: SMTPServer) -> None:
        """Verify the sender address includes a MIME subtype when given.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        sender = smtp_server_mail("+test")
        assert sender == "pytest+test@localhost"


class TestSendEmail:
    """Verify email delivery via the in-process SMTP server."""

    @pytest.mark.asyncio
    async def test_send_email(self, smtp: SMTPServer) -> None:
        """Verify a single email is delivered with correct subject and body.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        msg = MIMEText("Hello from test")
        msg["Subject"] = "Test Subject"
        await send_email("recipient@test.com", msg)

        assert len(smtp.outbox) == 1
        received = smtp.outbox[0]
        assert "recipient@test.com" in received["To"]

    @pytest.mark.asyncio
    async def test_send_multiple_emails(self, smtp: SMTPServer) -> None:
        """Verify multiple emails can be delivered in one call.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        for i in range(3):
            msg = MIMEText(f"Message {i}")
            msg["Subject"] = f"Subject {i}"
            await send_email(f"user{i}@test.com", msg)

        assert len(smtp.outbox) == 3


class TestSendSms:
    """Verify SMS delivery via SMS-to-email gateway."""

    @pytest.mark.asyncio
    async def test_send_sms(self, smtp: SMTPServer) -> None:
        """send_sms should route through carrier gateway email address.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        msg = MIMEText("SMS test message")
        msg["Subject"] = "SMS"
        await send_sms("5551234567", "tmomail.net", msg)

        assert len(smtp.outbox) == 1
        received = smtp.outbox[0]
        assert "5551234567@tmomail.net" in received["To"]

    @pytest.mark.asyncio
    async def test_send_sms_with_subtype(self, smtp: SMTPServer) -> None:
        """send_sms should support _from_subtype.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        """
        msg = MIMEText("SMS subtype test")
        msg["Subject"] = "SMS"
        await send_sms("5559876543", "vzwpix.com", msg, _from_subtype="+sms")

        assert len(smtp.outbox) == 1
        received = smtp.outbox[0]
        assert "5559876543@vzwpix.com" in received["To"]
        assert "+sms@" in received["From"]


def _make_location(s: Session, name: str = "Notify Bar") -> Location:
    """Create a test happy-hour location.

    :param s: Active database session.
    :type s: Session
    :param name: Location name.
    :type name: str
    :returns: The persisted location.
    :rtype: Location
    """
    from db.functions import create_location

    return create_location(
        s,
        Name=name,
        URL="https://notifybar.com",
        AddressRaw="456 Notify Ave",
        Number=456,
        StreetName="Notify Ave",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )


class TestNotifyHappyHourUsers:
    """Verify :func:`notify_happy_hour_users` dispatches emails and SMS."""

    @pytest.mark.asyncio
    async def test_notify_email_only_users(
        self, smtp: SMTPServer, db_session: Session
    ) -> None:
        """Users with email but no phone should get email only.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "emailuser",
            "emailuser@test.com",
            ExternalAuthProvider.test,
            "eu1",
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        loc = _make_location(db_session, name="Email Bar")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
            description="Email notification test",
        )

        await notify_happy_hour_users(event, db_session)

        assert len(smtp.outbox) == 1
        assert "emailuser@test.com" in smtp.outbox[0]["To"]

    @pytest.mark.asyncio
    async def test_notify_phone_and_email_users(
        self, smtp: SMTPServer, db_session: Session
    ) -> None:
        """Users with both email and phone should get both notifications.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "bothuser",
            "bothuser@test.com",
            ExternalAuthProvider.test,
            "bu1",
            phone="5551112222",
            phone_provider=PhoneProvider.TMOBILE,
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        loc = _make_location(db_session, name="Both Bar")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
            description="Dual notification test",
        )

        await notify_happy_hour_users(event, db_session)

        # Should get an email + an SMS
        assert len(smtp.outbox) == 2
        recipients = [m["To"] for m in smtp.outbox]
        assert any("bothuser@test.com" in r for r in recipients)
        assert any("5551112222@tmomail.net" in r for r in recipients)

    @pytest.mark.asyncio
    async def test_notify_phone_only_user(
        self, smtp: SMTPServer, db_session: Session
    ) -> None:
        """Users with phone but no email should get SMS only.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "phoneuser",
            None,
            ExternalAuthProvider.test,
            "pu1",
            phone="5553334444",
            phone_provider=PhoneProvider.VERIZON,
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        loc = _make_location(db_session, name="Phone Bar")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
            description="Phone notification test",
        )

        await notify_happy_hour_users(event, db_session)

        assert len(smtp.outbox) == 1
        assert "5553334444@vzwpix.com" in smtp.outbox[0]["To"]

    @pytest.mark.asyncio
    async def test_notify_skips_users_without_claim(
        self, smtp: SMTPServer, db_session: Session
    ) -> None:
        """Users without HAPPY_HOUR claim should not get notified.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "noclaim",
            "noclaim@test.com",
            ExternalAuthProvider.test,
            "nc1",
            claims=AccountClaims.MEALBOT,
        )
        db_session.add(act)
        db_session.commit()

        loc = _make_location(db_session, name="NoClaim Bar")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )

        await notify_happy_hour_users(event, db_session)

        assert len(smtp.outbox) == 0

    @pytest.mark.asyncio
    async def test_notify_skips_phone_none_provider(
        self, smtp: SMTPServer, db_session: Session
    ) -> None:
        """Users with phone but NONE provider should not get SMS.

        :param smtp: In-process SMTP server.
        :type smtp: SMTPServer
        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        act = create_account(
            "noprovider",
            "noprovider@test.com",
            ExternalAuthProvider.test,
            "np1",
            phone="5555556666",
            phone_provider=PhoneProvider.NONE,
            claims=AccountClaims.HAPPY_HOUR,
        )
        db_session.add(act)
        db_session.commit()

        loc = _make_location(db_session, name="NoProvider Bar")
        event = create_event(
            db_session,
            loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )

        await notify_happy_hour_users(event, db_session)

        # Should only get email, not SMS
        assert len(smtp.outbox) == 1
        assert "noprovider@test.com" in smtp.outbox[0]["To"]
