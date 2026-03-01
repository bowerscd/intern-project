"""Tests for Event model methods: repr, text(), email(), and description handling."""
import pytest
from datetime import datetime, UTC, timedelta

from models.enums import AccountClaims
from models import ExternalAuthProvider
from db.functions import create_account, create_location, create_event
from typing import Any
from models.happyhour.location import Location
from email.message import Message
from sqlalchemy.orm import Session


class TestEventRepr:
    """Verify :meth:`Event.__repr__` output."""
    def test_event_repr(self, db_session: Session) -> None:
        """Verify the repr string includes the event's location name.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Repr Bar")
        act = create_account("repruser", "repr@test.com", ExternalAuthProvider.test, "rpu1",
                             claims=AccountClaims.HAPPY_HOUR)
        db_session.add(act)
        db_session.commit()

        event = create_event(
            db_session, loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
            description="Repr test",
        )
        r = repr(event)
        assert "HappyHourEvent" in r


class TestEventText:
    """Verify event plain-text rendering."""
    def test_text_includes_location_name(self, db_session: Session) -> None:
        """Verify the text body contains the location name.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Text Bar")
        act = create_account("textuser", "text@test.com", ExternalAuthProvider.test, "tu1",
                             claims=AccountClaims.HAPPY_HOUR)
        db_session.add(act)
        db_session.commit()

        event = create_event(
            db_session, loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )
        msg = event.text()
        payload = msg.get_payload(decode=True).decode()
        assert "Text Bar" in payload

    def test_text_includes_url_when_present(self, db_session: Session) -> None:
        """text() should include URL when location has one.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="URL Bar", URL="https://urlbar.com")
        act = create_account("urltextuser", "urltext@test.com", ExternalAuthProvider.test, "utu1",
                             claims=AccountClaims.HAPPY_HOUR)
        db_session.add(act)
        db_session.commit()

        event = create_event(
            db_session, loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )
        msg = event.text()
        payload = msg.get_payload(decode=True).decode()
        assert "https://urlbar.com" in payload

    def test_text_omits_none_url(self, db_session: Session) -> None:
        """text() should not contain 'None' when location has no URL.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="NoURL Bar", URL=None)
        act = create_account("nourltextuser", "nourltext@test.com", ExternalAuthProvider.test, "nutu1",
                             claims=AccountClaims.HAPPY_HOUR)
        db_session.add(act)
        db_session.commit()

        event = create_event(
            db_session, loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )
        msg = event.text()
        payload = msg.get_payload(decode=True).decode()
        assert "NoURL Bar" in payload
        assert "None" not in payload


class TestEventEmail:
    """Verify event MIME-email rendering."""
    def test_email_has_subject(self, db_session: Session) -> None:
        """Verify the email includes a subject header.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Email Bar")
        act = create_account("emailevtuser", "emailevt@test.com", ExternalAuthProvider.test, "eeu1",
                             claims=AccountClaims.HAPPY_HOUR)
        db_session.add(act)
        db_session.commit()

        event = create_event(
            db_session, loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )
        msg = event.email()
        assert msg["Subject"] is not None
        assert "Happy Hour" in msg["Subject"]

    def test_email_without_url_has_no_broken_href(self, db_session: Session) -> None:
        """email() should not produce broken HTML when location has no URL.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="NoURL Email Bar", URL=None)
        act = create_account("nourlemailuser", "nourlemail@test.com", ExternalAuthProvider.test, "nueu1",
                             claims=AccountClaims.HAPPY_HOUR)
        db_session.add(act)
        db_session.commit()

        event = create_event(
            db_session, loc.id,
            datetime.now(UTC) + timedelta(days=2),
            tyrant_id=act.id,
        )
        msg = event.email()
        assert msg["Subject"] is not None
        assert "Happy Hour" in msg["Subject"]
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == 'text/html':
                html = part.get_payload(decode=True).decode()
                assert 'href="None"' not in html
                assert "NoURL Email Bar" in html


class TestEventDescriptionBypassesHtmlTemplate:
    """
    When Description is not None, both __summary_text and __summary_html
    return the raw description string. The HTML version is NOT valid HTML —
    it's a bare string used as text/html in the email.
    """

    def test_description_bypasses_html_template(self, db_session: Session) -> None:
        """An event with Description gets a bare string for HTML, not a full template.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Template Bar")
        a = create_account("tmpl1", "t@t.com", ExternalAuthProvider.test, "tmpl1")
        db_session.add(a)
        db_session.commit()

        event = create_event(
            db_session, loc.id, when=datetime.now(UTC),
            tyrant_id=a.id, description="Auto-selected: Template Bar",
        )

        email_msg = event.email()
        html_content = _extract_html_from_email(email_msg)

        assert html_content is not None, "Should have an HTML part"
        assert "<html>" not in html_content.lower(), (
            "Description bypasses HTML template — bare string used as HTML"
        )
        assert "Address:" not in html_content, (
            "No address info in email when description is set"
        )

    def test_no_description_uses_full_html_template(self, db_session: Session) -> None:
        """An event without Description uses the full HTML template.

        :param db_session: SQLAlchemy database session.
        :type db_session: Session
        """
        loc = _make_location(db_session, name="Full Template Bar")
        a = create_account("tmpl2", "t2@t.com", ExternalAuthProvider.test, "tmpl2")
        db_session.add(a)
        db_session.commit()

        event = create_event(
            db_session, loc.id, when=datetime.now(UTC),
            tyrant_id=a.id, description=None,
        )

        email_msg = event.email()
        html_content = _extract_html_from_email(email_msg)

        assert html_content is not None, "Should have an HTML part"
        assert "<html>" in html_content.lower(), (
            "Without description, the full HTML template is used"
        )


def _extract_html_from_email(msg: Message) -> str | None:
    """Extract text/html content from nested MIME structure.

    :param msg: MIME email message to inspect.
    :type msg: email.message.Message
    :returns: ``text/html`` body, or ``None`` if absent.
    :rtype: str | None
    """
    for part in msg.walk():
        if part.get_content_type() == 'text/html':
            data = part.get_payload(decode=True)
            return data.decode() if data else None
    return None


def _make_location(s: Session, name: str = "Event Test Bar", **overrides: Any) -> Location:
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
        URL="https://eventtestbar.com",
        AddressRaw="321 Event Ave",
        Number=321,
        StreetName="Event Ave",
        City="Testville",
        State="TS",
        ZipCode="12345",
        Latitude=37.7749,
        Longitude=-122.4194,
    )
    defaults.update(overrides)
    return create_location(s, **defaults)
