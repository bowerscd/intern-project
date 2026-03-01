"""Happy hour event ORM model with email, SMS, and iCalendar renderers."""

from typing import Optional
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape as html_escape

from icalendar import Calendar as ICalendar

from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server import hostname, api_server

from models.database import Model
from models.happyhour.location import Location
from models.account import Account


class Event(Model):
    """Happy hour event persisted in the ``HappyHourEvents`` table.

    Associates a location, date, and optional tyrant chooser with each
    scheduled happy hour gathering.  Also provides helpers that render
    email, SMS, and iCalendar representations of the event.
    """

    __tablename__ = "HappyHourEvents"
    __table_args__ = (UniqueConstraint("week_of", name="uq_events_week_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    Description: Mapped[Optional[str]] = mapped_column(String)
    When: Mapped[datetime] = mapped_column(
        insert_default=lambda: datetime.now(UTC), index=True
    )
    week_of: Mapped[str] = mapped_column(String(8))
    LocationID: Mapped[int] = mapped_column(ForeignKey("HappyHourLocations.id"))
    Location: Mapped["Location"] = relationship("Location")
    TyrantID: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    Tyrant: Mapped[Optional[Account]] = relationship("Account")
    AutoSelected: Mapped[bool] = mapped_column(default=False)

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the event.

        :returns: A string showing the location and chooser.
        :rtype: str
        """
        chooser = self.Tyrant.username if self.Tyrant else "System"
        return f"<HappyHourEvent Loc={self.Location} Chooser={chooser}>"

    @property
    def __summary_text(self) -> str:
        """Build a plain-text summary of the event for notifications.

        :returns: Multi-line plain-text event summary.
        :rtype: str
        """
        if self.Description is not None:
            return self.Description
        date = self.When.date().strftime("%d-%m-%y")
        chosen_by = self.Tyrant.username if self.Tyrant else "Auto-selected by system"
        url_line = f"\n{self.Location.URL}" if self.Location.URL else ""
        return f"""The happy hour on {date}, will be at {self.Location.Name}.
This week was chosen by {chosen_by}.
Address:
{self.Location.AddressRaw}{url_line}
Cheers,
Happy Hour Bot
        """

    @property
    def __summary_html(self) -> str:
        """Build an HTML summary of the event for email notifications.

        :returns: HTML-formatted event summary.
        :rtype: str
        """
        if self.Description is not None:
            return html_escape(self.Description)
        date = self.When.date().strftime("%d-%m-%y")
        if self.Location.URL:
            venue = f'<a href="{html_escape(self.Location.URL)}">{html_escape(self.Location.Name)}</a>'
        else:
            venue = html_escape(self.Location.Name)
        chooser = (
            html_escape(self.Tyrant.username)
            if self.Tyrant
            else "Auto-selected by system"
        )
        return f"""
<!doctype html>
<html>
    <head>
        <meta charset="UTF-8" />
    </head>
    <body>
        <p>Hello,</p>
        <p>The happy hour on {date}, will be at {venue}.</p>
        <p>This week was chosen by {chooser}.</p>
        <br/>
        <p>Address:</p>
        <p>{html_escape(self.Location.AddressRaw)}</p>
        <br/>
        <p>Cheers,</p>
        <p>Happy Hour Bot</p>
    </body>
</html>
"""

    @property
    def __ical(self) -> ICalendar:
        """Build an iCalendar object for the event.

        The event is scheduled from 4 PM to 5 PM Pacific on the event
        date.

        :returns: A populated :class:`icalendar.Calendar` instance.
        :rtype: ICalendar
        """
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo
        from icalendar import Calendar, Event as ICalEvent, vUri

        FOUR_PM = 16
        FIVE_PM = 17

        TZ = ZoneInfo("US/Pacific")
        event_date = self.When.date()
        st = dt(event_date.year, event_date.month, event_date.day, FOUR_PM, tzinfo=TZ)
        end = dt(event_date.year, event_date.month, event_date.day, FIVE_PM, tzinfo=TZ)

        e = ICalEvent()
        e.add("SUMMARY", "Happy Hour")
        e.add("DTSTART", st)
        e.add("DTEND", end)
        e.add("DTSTAMP", dt.now(UTC))
        e.add("DESCRIPTION", f"{self.__summary_text}")
        e.add("LOCATION", self.Location.AddressRaw)
        e.add("UID", f"{self.id}@{hostname()}")
        uri = vUri.from_ical(f"{api_server()}/api/v2/happyhour/events/{self.id}")
        e.add("URI", uri)

        ic = Calendar()
        ic.add_component(e)
        ic.add("METHOD", "REQUEST")
        ic.add("VERSION", "2.0")
        ic.add("PRODID", "-//Happy Hour Bot//EN")
        ic.add("CALSCALE", "GREGORIAN")
        ic.add_missing_timezones()

        return ic

    def text(self) -> MIMEText:
        """Build a plain-text MIME message for SMS or simple email delivery.

        :returns: A ``text/plain`` MIME part containing the event details.
        :rtype: MIMEText
        """
        date = self.When.date().strftime("%d-%m-%y")
        url_line = f"\n{self.Location.URL}" if self.Location.URL else ""
        msg = f"""The happy hour on {date}, will be at {self.Location.Name}.
Address:
{self.Location.AddressRaw}{url_line}
"""
        return MIMEText(msg, "plain", "utf-8")

    def email(self) -> MIMEMultipart:
        """Build a full multipart email message with iCalendar attachment.

        The message contains a calendar invitation, a plain-text
        fallback, and an HTML alternative.

        :returns: A ``multipart/mixed`` MIME message.
        :rtype: MIMEMultipart
        """
        date = self.When.date().strftime("%d-%m-%y")
        calendar = MIMEText(self.__ical.to_ical().decode(), "calendar", "utf-8")
        calendar.set_param("method", "REQUEST", requote=False)
        calendar.set_param("name", "happyhour.ics")
        calendar.add_header(
            "Content-Disposition", "attachment", filename="happyhour.ics"
        )
        plain_text = MIMEText(self.__summary_text, "plain", "utf-8")
        html_alt = MIMEText(self.__summary_html, "html", "utf-8")
        msg_content = MIMEMultipart(
            "alternative", _subparts=(plain_text, html_alt, calendar)
        )
        msg = MIMEMultipart("mixed")
        msg.attach(msg_content)
        msg["Subject"] = f"Happy Hour {date}"
        return msg
