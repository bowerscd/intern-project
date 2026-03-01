"""Outgoing email and SMS delivery via async SMTP."""

import logging
from typing import Any

from email.message import Message
from email.mime.text import MIMEText

from . import smtp_cfg, smtp_server_mail

logger = logging.getLogger(__name__)


async def send_email(to: str, msg: Message, _from_subtype: str = "") -> None:
    """Send an email via async SMTP.

    Creates a copy of the message to avoid mutating the caller's object
    when setting To/From headers.  In ``DEV`` mode TLS and
    authentication are skipped.

    :param to: Recipient email address.
    :param msg: The email :class:`~email.message.Message` to send.
    :param _from_subtype: Optional sub-address tag for the sender.
    """
    import copy
    import aiosmtplib
    from config import DEV_MODE

    cfg = smtp_cfg()

    # Work on a copy to avoid header accumulation when callers reuse messages
    msg_copy = copy.deepcopy(msg)
    del msg_copy["To"]
    del msg_copy["From"]
    msg_copy["To"] = to
    msg_copy["From"] = smtp_server_mail(_from_subtype)

    if not DEV_MODE:
        await aiosmtplib.send(
            msg_copy,
            hostname=cfg.Hostname,
            port=cfg.Port,
            start_tls=True,
            username=cfg.Username,
            password=cfg.Password,
        )
    else:
        await aiosmtplib.send(
            msg_copy,
            hostname=cfg.Hostname,
            port=cfg.Port,
        )


async def send_sms(
    phone: str, gateway: str, msg: Message, _from_subtype: str = ""
) -> None:
    """Send an SMS via a carrier's email-to-SMS gateway.

    :param phone: Recipient phone number (digits only).
    :param gateway: The carrier's MMS gateway domain.
    :param msg: The :class:`~email.message.Message` to deliver.
    :param _from_subtype: Optional sub-address tag for the sender.
    """
    sms_address = f"{phone}@{gateway}"
    await send_email(sms_address, msg, _from_subtype)


async def _notify_user(account: Any, email_msg: Message, sms_msg: Message) -> None:
    """Send email and/or SMS to a user based on their contact information.

    :param account: An :class:`Account` instance with ``email``, ``phone``,
        and ``phone_provider`` attributes.
    :param email_msg: The email message to send if the user has an email.
    :param sms_msg: The SMS message to send if the user has a phone number
        and carrier gateway.
    """
    from models.enums import PhoneProvider

    if account.email:
        await send_email(account.email, email_msg)

    if account.phone and account.phone_provider != PhoneProvider.NONE:
        gateway = account.phone_provider.gateway
        if gateway:
            await send_sms(account.phone, gateway, sms_msg)


async def notify_happy_hour_users(event: Any, db_session: Any) -> None:
    """Send happy hour notifications to all users with the ``HAPPY_HOUR`` claim.

    Sends an email to users with an email address and an SMS to users
    with a phone number and carrier gateway.

    :param event: An :class:`Event` instance providing ``email()`` and
        ``text()`` message builders.
    :param db_session: An active database session used to query eligible
        accounts.
    """
    from models.enums import AccountClaims
    from db.functions import get_accounts_with_claim

    users = get_accounts_with_claim(db_session, AccountClaims.HAPPY_HOUR)

    import asyncio

    results = await asyncio.gather(
        *[_notify_user(user, event.email(), event.text()) for user in users],
        return_exceptions=True,
    )
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Failed to notify user {users[i].username}: {result}")


async def notify_tyrant_assigned(account: Any, deadline_at: Any) -> None:
    """Notify a user that they have been assigned as this week's tyrant.

    Sends an email and/or SMS depending on the account's contact
    information.

    :param account: The :class:`Account` assigned as tyrant.
    :param deadline_at: A :class:`~datetime.datetime` by which the tyrant
        must choose a venue.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Los_Angeles")
    deadline_local = deadline_at.astimezone(tz) if deadline_at.tzinfo else deadline_at

    deadline_str = deadline_local.strftime("%A, %B %d at %I:%M %p %Z")

    subject = "It's your turn to pick Happy Hour!"
    body = (
        f"Hi {account.username},\n\n"
        f"You've been selected as this week's happy hour tyrant! "
        f"Please choose a location and create the event before the deadline:\n\n"
        f"  Deadline: {deadline_str}\n\n"
        f"If you don't pick by the deadline, a location will be auto-selected.\n\n"
        f"Cheers,\nHappy Hour Bot"
    )

    email_msg = MIMEText(body, "plain", "utf-8")
    email_msg["Subject"] = subject
    sms_msg = MIMEText(body, "plain", "utf-8")

    await _notify_user(account, email_msg, sms_msg)


async def notify_tyrant_on_deck(account: Any, current_tyrant_name: str) -> None:
    """Notify a user that they are next in the tyrant rotation.

    Sends an "on deck" heads-up so the user can start thinking about
    venue options before their turn officially begins.

    :param account: The :class:`Account` who is on deck.
    :param current_tyrant_name: Username of the currently assigned tyrant.
    """
    subject = "You're on deck for Happy Hour next week!"
    body = (
        f"Hi {account.username},\n\n"
        f"Heads up — you're next in the happy hour rotation! "
        f"{current_tyrant_name} is picking this week, and you'll be up next.\n\n"
        f"Start thinking about where you'd like to take the crew!\n\n"
        f"Cheers,\nHappy Hour Bot"
    )

    email_msg = MIMEText(body, "plain", "utf-8")
    email_msg["Subject"] = subject
    sms_msg = MIMEText(body, "plain", "utf-8")

    await _notify_user(account, email_msg, sms_msg)
