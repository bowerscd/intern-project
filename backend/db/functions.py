"""
Database helper functions for account, mealbot, and happy hour operations.
"""
from typing import Any, Optional
from datetime import datetime, UTC

from sqlalchemy import select, func, and_, or_, literal
from sqlalchemy.orm import Session, joinedload

from models import (
    DBAccount as Account,
    DBReceipt as Receipt,
    DBEvent as Event,
    DBLocation as Location,
    DBTyrantRotation as TyrantRotation,
    ExternalAuthProvider,
    PhoneProvider,
    AccountClaims,
    TyrantAssignmentStatus,
)


# --- Account functions ---

def create_account(
    username: str,
    email: Optional[str],
    account_provider: ExternalAuthProvider,
    external_unique_id: str,
    phone: str | None = None,
    phone_provider: PhoneProvider = PhoneProvider.NONE,
    claims: AccountClaims = AccountClaims.NONE
) -> Account:
    """Create a new account instance without persisting it to the database.

    :param username: Unique username for the account.
    :param email: Email address, or ``None`` if not provided.
    :param account_provider: External authentication provider.
    :param external_unique_id: Unique identifier from the external provider.
    :param phone: Phone number, or ``None`` if not provided.
    :param phone_provider: Phone carrier provider.
    :param claims: Bitmask of account claims/permissions.
    :returns: A new, unsaved :class:`Account` instance.
    :rtype: Account
    """
    act = Account(
        username=username,
        email=email,
        phone=phone,
        phone_provider=phone_provider,
        account_provider=account_provider,
        external_unique_id=external_unique_id,
        claims=claims,
    )
    return act


def get_account_by_email(s: Session, email: str) -> Account | None:
    """Look up an account by email address.

    :param s: Active database session.
    :param email: The email address to search for.
    :returns: The matching account, or ``None`` if not found.
    :rtype: Account | None
    """
    return s.scalars(select(Account).where(Account.email == email)).first()


def get_account_by_phone(s: Session, phone: str) -> Account | None:
    """Look up an account by phone number.

    :param s: Active database session.
    :param phone: The phone number to search for.
    :returns: The matching account, or ``None`` if not found.
    :rtype: Account | None
    """
    return s.scalars(select(Account).where(Account.phone == phone)).first()


def get_account_by_username(s: Session, username: str) -> Account | None:
    """Look up an account by username.

    :param s: Active database session.
    :param username: The username to search for.
    :returns: The matching account, or ``None`` if not found.
    :rtype: Account | None
    """
    return s.scalars(select(Account).where(Account.username == username)).first()


def get_account_by_id(s: Session, account_id: int) -> Account | None:
    """Look up an account by its primary key.

    :param s: Active database session.
    :param account_id: The account's integer ID.
    :returns: The matching account, or ``None`` if not found.
    :rtype: Account | None
    """
    return s.scalars(select(Account).where(Account.id == account_id)).first()


def get_account_by_provider(
    s: Session,
    provider: ExternalAuthProvider,
    external_id: str,
) -> Account | None:
    """Look up an account by external auth provider and external ID.

    :param s: Active database session.
    :param provider: The external authentication provider.
    :param external_id: The unique identifier from the external provider.
    :returns: The matching account, or ``None`` if not found.
    :rtype: Account | None
    """
    return s.scalars(
        select(Account).where(
            and_(
                Account.account_provider == provider,
                Account.external_unique_id == external_id,
            )
        )
    ).first()


def get_all_accounts(s: Session) -> list[Account]:
    """Retrieve all accounts from the database.

    :param s: Active database session.
    :returns: A list of all accounts.
    :rtype: list[Account]
    """
    return s.scalars(select(Account)).all()


# --- Mealbot functions ---

def create_receipt(
    s: Session,
    payer_username: str,
    recipient_username: str,
    credits: int,
    recorder_id: int | None = None,
) -> Receipt:
    """Create and persist a meal receipt recording a credit transfer.

    :param s: Active database session.
    :param payer_username: Username of the account paying credits.
    :param recipient_username: Username of the account receiving credits.
    :param credits: Number of credits transferred.
    :param recorder_id: Account ID of the user who recorded this receipt, or
        ``None`` if recorded automatically.
    :returns: The newly created and committed receipt.
    :rtype: Receipt
    :raises ValueError: If the payer or recipient username does not exist, or
        if the payer and recipient are the same person.
    """
    payer = get_account_by_username(s, payer_username)
    if payer is None:
        raise ValueError(f"Payer '{payer_username}' does not exist")

    recipient = get_account_by_username(s, recipient_username)
    if recipient is None:
        raise ValueError(f"Recipient '{recipient_username}' does not exist")

    if payer.id == recipient.id:
        raise ValueError("Payer and recipient cannot be the same person")

    receipt = Receipt(
        Credits=credits,
        Time=datetime.now(UTC),
        PayerId=payer.id,
        RecipientId=recipient.id,
        RecorderId=recorder_id,
    )
    s.add(receipt)
    s.flush()
    return receipt


def get_all_records(s: Session) -> list[Receipt]:
    """Retrieve all receipts ordered by time descending.

    :param s: Active database session.
    :returns: A list of all receipts, newest first.
    :rtype: list[Receipt]
    """
    return s.scalars(
        select(Receipt).order_by(Receipt.Time.desc())
    ).all()


def count_records(s: Session) -> int:
    """Count total number of receipts.

    :param s: Active database session.
    :returns: The total receipt count.
    :rtype: int
    """
    return s.execute(select(func.count()).select_from(Receipt)).scalar() or 0


def get_records_paginated(s: Session, offset: int, limit: int) -> list[Receipt]:
    """Retrieve a page of receipts ordered by time descending.

    :param s: Active database session.
    :param offset: Number of rows to skip.
    :param limit: Maximum number of rows to return.
    :returns: A page of receipts, newest first.
    :rtype: list[Receipt]
    """
    return s.scalars(
        select(Receipt)
        .options(joinedload(Receipt.Payer), joinedload(Receipt.Recipient))
        .order_by(Receipt.Time.desc()).offset(offset).limit(limit)
    ).all()


def get_records_with_limit(s: Session, limit: int) -> list[Receipt]:
    """Retrieve the most recent receipts up to a given limit.

    :param s: Active database session.
    :param limit: Maximum number of receipts to return.
    :returns: A list of the most recent receipts, newest first.
    :rtype: list[Receipt]
    """
    return s.scalars(
        select(Receipt).order_by(Receipt.Time.desc()).limit(limit)
    ).all()


def get_records_for_user(s: Session, username: str, limit: int | None = None) -> list[Receipt]:
    """Retrieve receipts involving a specific user as payer or recipient.

    :param s: Active database session.
    :param username: The username to filter by.
    :param limit: Maximum number of receipts to return, or ``None`` for all.
    :returns: A list of matching receipts, newest first.
    :rtype: list[Receipt]
    :raises ValueError: If the username does not exist.
    """
    user = get_account_by_username(s, username)
    if user is None:
        raise ValueError(f"User '{username}' does not exist")

    stmt = select(Receipt).where(
        or_(Receipt.PayerId == user.id, Receipt.RecipientId == user.id)
    ).order_by(Receipt.Time.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return s.scalars(stmt).all()


def count_records_for_user(s: Session, username: str) -> int:
    """Count receipts involving a specific user as payer or recipient.

    :param s: Active database session.
    :param username: The username to filter by.
    :returns: The total count of matching receipts.
    :rtype: int
    :raises ValueError: If the username does not exist.
    """
    user = get_account_by_username(s, username)
    if user is None:
        raise ValueError(f"User '{username}' does not exist")

    return s.execute(
        select(func.count()).select_from(Receipt).where(
            or_(Receipt.PayerId == user.id, Receipt.RecipientId == user.id)
        )
    ).scalar() or 0


def get_records_for_user_paginated(
    s: Session,
    username: str,
    offset: int,
    limit: int,
) -> list[Receipt]:
    """Retrieve a page of receipts involving a specific user.

    :param s: Active database session.
    :param username: The username to filter by.
    :param offset: Number of rows to skip.
    :param limit: Maximum number of rows to return.
    :returns: A page of matching receipts, newest first.
    :rtype: list[Receipt]
    :raises ValueError: If the username does not exist.
    """
    user = get_account_by_username(s, username)
    if user is None:
        raise ValueError(f"User '{username}' does not exist")

    return s.scalars(
        select(Receipt)
        .options(joinedload(Receipt.Payer), joinedload(Receipt.Recipient))
        .where(
            or_(Receipt.PayerId == user.id, Receipt.RecipientId == user.id)
        ).order_by(Receipt.Time.desc()).offset(offset).limit(limit)
    ).all()


def get_records_between_users(
    s: Session,
    username1: str,
    username2: str,
    limit: int | None = None,
) -> list[Receipt]:
    """Retrieve receipts exchanged between two specific users.

    :param s: Active database session.
    :param username1: The first username.
    :param username2: The second username.
    :param limit: Maximum number of receipts to return, or ``None`` for all.
    :returns: A list of matching receipts, newest first.
    :rtype: list[Receipt]
    :raises ValueError: If either username does not exist.
    """
    user1 = get_account_by_username(s, username1)
    if user1 is None:
        raise ValueError(f"User '{username1}' does not exist")
    user2 = get_account_by_username(s, username2)
    if user2 is None:
        raise ValueError(f"User '{username2}' does not exist")

    stmt = select(Receipt).where(
        or_(
            and_(Receipt.PayerId == user1.id, Receipt.RecipientId == user2.id),
            and_(Receipt.PayerId == user2.id, Receipt.RecipientId == user1.id),
        )
    ).order_by(Receipt.Time.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return s.scalars(stmt).all()


def get_timebound_records(
    s: Session,
    start: datetime,
    end: datetime,
    limit: int | None = None,
) -> list[Receipt]:
    """Retrieve receipts within a time range.

    :param s: Active database session.
    :param start: Inclusive lower bound of the time range.
    :param end: Inclusive upper bound of the time range.
    :param limit: Maximum number of receipts to return, or ``None`` for all.
    :returns: A list of matching receipts, newest first.
    :rtype: list[Receipt]
    """
    stmt = select(Receipt).where(
        and_(Receipt.Time >= start, Receipt.Time <= end)
    ).order_by(Receipt.Time.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return s.scalars(stmt).all()


def get_timebound_records_for_user(
    s: Session,
    username: str,
    start: datetime,
    end: datetime,
    limit: int | None = None,
) -> list[Receipt]:
    """Retrieve receipts for a specific user within a time range.

    :param s: Active database session.
    :param username: The username to filter by.
    :param start: Inclusive lower bound of the time range.
    :param end: Inclusive upper bound of the time range.
    :param limit: Maximum number of receipts to return, or ``None`` for all.
    :returns: A list of matching receipts, newest first.
    :rtype: list[Receipt]
    :raises ValueError: If the username does not exist.
    """
    user = get_account_by_username(s, username)
    if user is None:
        raise ValueError(f"User '{username}' does not exist")

    stmt = select(Receipt).where(
        and_(
            or_(Receipt.PayerId == user.id, Receipt.RecipientId == user.id),
            Receipt.Time >= start,
            Receipt.Time <= end,
        )
    ).order_by(Receipt.Time.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return s.scalars(stmt).all()


def get_timebound_records_between_users(
    s: Session,
    username1: str,
    username2: str,
    start: datetime,
    end: datetime,
    limit: int | None = None,
) -> list[Receipt]:
    """Retrieve receipts between two users within a time range.

    :param s: Active database session.
    :param username1: The first username.
    :param username2: The second username.
    :param start: Inclusive lower bound of the time range.
    :param end: Inclusive upper bound of the time range.
    :param limit: Maximum number of receipts to return, or ``None`` for all.
    :returns: A list of matching receipts, newest first.
    :rtype: list[Receipt]
    :raises ValueError: If either username does not exist.
    """
    user1 = get_account_by_username(s, username1)
    if user1 is None:
        raise ValueError(f"User '{username1}' does not exist")
    user2 = get_account_by_username(s, username2)
    if user2 is None:
        raise ValueError(f"User '{username2}' does not exist")

    stmt = select(Receipt).where(
        and_(
            or_(
                and_(Receipt.PayerId == user1.id, Receipt.RecipientId == user2.id),
                and_(Receipt.PayerId == user2.id, Receipt.RecipientId == user1.id),
            ),
            Receipt.Time >= start,
            Receipt.Time <= end,
        )
    ).order_by(Receipt.Time.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return s.scalars(stmt).all()


def get_global_summary(
    s: Session,
) -> dict[str, dict[str, dict[str, int]]]:
    """Compute a global credit summary across all accounts.

    Uses SQL aggregation instead of loading all records into Python.

    :param s: Active database session.
    :returns: Nested dict of the form
        ``{user1: {user2: {"incoming-credits": int, "outgoing-credits": int}}}``.
    :rtype: dict[str, dict[str, dict[str, int]]]
    """
    accounts = get_all_accounts(s)
    account_map = {a.id: a.username for a in accounts}

    result: dict[str, dict[str, dict[str, int]]] = {}
    for a in accounts:
        result[a.username] = {}
        for b in accounts:
            if a.id != b.id:
                result[a.username][b.username] = {
                    "incoming-credits": 0,
                    "outgoing-credits": 0,
                }

    # Aggregate credits at the SQL level
    rows = s.execute(
        select(Receipt.PayerId, Receipt.RecipientId, func.sum(Receipt.Credits).label("total"))
        .group_by(Receipt.PayerId, Receipt.RecipientId)
    ).all()

    for payer_id, recip_id, total in rows:
        payer_name = account_map.get(payer_id, "")
        recip_name = account_map.get(recip_id, "")
        if payer_name and recip_name and payer_name != recip_name:
            result[payer_name][recip_name]["outgoing-credits"] += total
            result[recip_name][payer_name]["incoming-credits"] += total

    return result


def get_summary_for_user(
    s: Session,
    username: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, dict[str, int]]:
    """Compute a credit summary for a single user against all other accounts.

    Uses SQL aggregation instead of loading all receipts into Python.
    Optionally filtered to a specific time range.

    :param s: Active database session.
    :param username: The username to compute the summary for.
    :param start: Inclusive lower time bound, or ``None`` for unbounded.
    :param end: Inclusive upper time bound, or ``None`` for unbounded.
    :returns: Dict of the form
        ``{other_user: {"incoming-credits": int, "outgoing-credits": int}}``.
    :rtype: dict[str, dict[str, int]]
    :raises ValueError: If the username does not exist.
    """
    user = get_account_by_username(s, username)
    if user is None:
        raise ValueError(f"User '{username}' does not exist")

    accounts = get_all_accounts(s)
    account_map = {a.id: a.username for a in accounts}
    result: dict[str, dict[str, int]] = {}
    for a in accounts:
        if a.id != user.id:
            result[a.username] = {
                "incoming-credits": 0,
                "outgoing-credits": 0,
            }

    # Outgoing: user is the payer
    outgoing_filters = [Receipt.PayerId == user.id]
    if start is not None:
        outgoing_filters.append(Receipt.Time >= start)
    if end is not None:
        outgoing_filters.append(Receipt.Time <= end)

    outgoing_rows = s.execute(
        select(Receipt.RecipientId, func.sum(Receipt.Credits).label("total"))
        .where(and_(*outgoing_filters))
        .group_by(Receipt.RecipientId)
    ).all()

    for recip_id, total in outgoing_rows:
        recip_name = account_map.get(recip_id, "")
        if recip_name and recip_name in result:
            result[recip_name]["outgoing-credits"] += total

    # Incoming: user is the recipient
    incoming_filters = [Receipt.RecipientId == user.id]
    if start is not None:
        incoming_filters.append(Receipt.Time >= start)
    if end is not None:
        incoming_filters.append(Receipt.Time <= end)

    incoming_rows = s.execute(
        select(Receipt.PayerId, func.sum(Receipt.Credits).label("total"))
        .where(and_(*incoming_filters))
        .group_by(Receipt.PayerId)
    ).all()

    for payer_id, total in incoming_rows:
        payer_name = account_map.get(payer_id, "")
        if payer_name and payer_name in result:
            result[payer_name]["incoming-credits"] += total

    return result


# --- Happy Hour functions ---

def create_location(s: Session, **kwargs: Any) -> Location:
    """Create and persist a new happy hour location.

    :param s: Active database session.
    :param kwargs: Keyword arguments forwarded to the :class:`Location`
        constructor.
    :returns: The newly created and committed location.
    :rtype: Location
    """
    loc = Location(**kwargs)
    s.add(loc)
    s.flush()
    return loc


def get_all_locations(s: Session) -> list[Location]:
    """Retrieve all locations from the database.

    :param s: Active database session.
    :returns: A list of all locations.
    :rtype: list[Location]
    """
    return s.scalars(select(Location)).all()


def count_locations(s: Session) -> int:
    """Count total number of locations.

    :param s: Active database session.
    :returns: The total location count.
    :rtype: int
    """
    return s.execute(select(func.count()).select_from(Location)).scalar() or 0


def get_locations_paginated(s: Session, offset: int, limit: int) -> list[Location]:
    """Retrieve a page of locations.

    :param s: Active database session.
    :param offset: Number of rows to skip.
    :param limit: Maximum number of rows to return.
    :returns: A page of locations.
    :rtype: list[Location]
    """
    return s.scalars(
        select(Location).offset(offset).limit(limit)
    ).all()


def get_location_by_id(s: Session, location_id: int) -> Location | None:
    """Look up a location by its primary key.

    :param s: Active database session.
    :param location_id: The location's integer ID.
    :returns: The matching location, or ``None`` if not found.
    :rtype: Location | None
    """
    return s.scalars(select(Location).where(Location.id == location_id)).first()


def get_open_locations(s: Session) -> list[Location]:
    """Retrieve all locations that are not marked as closed.

    :param s: Active database session.
    :returns: A list of open locations.
    :rtype: list[Location]
    """
    return s.scalars(select(Location).where(Location.Closed == False)).all()  # noqa: E712


def _compute_week_of(when: datetime) -> str:
    """Compute ISO year-week string for duplicate event prevention.

    :param when: Event date/time.
    :returns: String like ``"2026-W09"``.
    :rtype: str
    """
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def create_event(
    s: Session,
    location_id: int,
    when: datetime,
    tyrant_id: int | None = None,
    description: str | None = None,
    auto_selected: bool = False,
) -> Event:
    """Create and persist a new happy hour event.

    :param s: Active database session.
    :param location_id: ID of the location where the event takes place.
    :param when: Date and time of the event.
    :param tyrant_id: Account ID of the tyrant who chose the location, or
        ``None`` if not assigned.
    :param description: Optional free-text description.
    :param auto_selected: Whether the location was automatically selected.
    :returns: The newly created and committed event.
    :rtype: Event
    """
    event = Event(
        LocationID=location_id,
        TyrantID=tyrant_id,
        When=when,
        Description=description,
        AutoSelected=auto_selected,
        week_of=_compute_week_of(when),
    )
    s.add(event)
    s.flush()
    return event


def get_all_events(s: Session) -> list[Event]:
    """Retrieve all events ordered by date descending.

    :param s: Active database session.
    :returns: A list of all events, newest first.
    :rtype: list[Event]
    """
    return s.scalars(select(Event).order_by(Event.When.desc())).all()


def count_events(s: Session) -> int:
    """Count total number of events.

    :param s: Active database session.
    :returns: The total event count.
    :rtype: int
    """
    return s.execute(select(func.count()).select_from(Event)).scalar() or 0


def get_events_paginated(s: Session, offset: int, limit: int) -> list[Event]:
    """Retrieve a page of events ordered by date descending.

    :param s: Active database session.
    :param offset: Number of rows to skip.
    :param limit: Maximum number of rows to return.
    :returns: A page of events, newest first.
    :rtype: list[Event]
    """
    return s.scalars(
        select(Event)
        .options(joinedload(Event.Location), joinedload(Event.Tyrant))
        .order_by(Event.When.desc()).offset(offset).limit(limit)
    ).all()


def get_event_by_id(s: Session, event_id: int) -> Event | None:
    """Look up an event by its primary key.

    :param s: Active database session.
    :param event_id: The event's integer ID.
    :returns: The matching event, or ``None`` if not found.
    :rtype: Event | None
    """
    return s.scalars(select(Event).where(Event.id == event_id)).first()


def get_upcoming_event(s: Session) -> Event | None:
    """Get the nearest future event.

    :param s: Active database session.
    :returns: The next upcoming event, or ``None`` if there are no future
        events.
    :rtype: Event | None
    """
    now = datetime.now(UTC)
    return s.scalars(
        select(Event)
        .options(joinedload(Event.Location), joinedload(Event.Tyrant))
        .where(Event.When >= now).order_by(Event.When.asc())
    ).first()


def get_events_this_week(s: Session, reference: datetime) -> list[Event]:
    """Get events within the current weekly window.

    The window starts at the most recent Wednesday 12:00 PM PST before
    *reference* and extends seven days forward.

    :param s: Active database session.
    :param reference: Reference datetime used to compute the weekly window.
    :returns: A list of events that fall within the weekly window.
    :rtype: list[Event]
    """
    from zoneinfo import ZoneInfo
    from datetime import timedelta

    tz = ZoneInfo("America/Los_Angeles")
    ref_local = reference.astimezone(tz)

    # Find previous Wednesday 12:00 PST
    days_since_wed = (ref_local.weekday() - 2) % 7
    last_wed = ref_local - timedelta(days=days_since_wed)
    last_wed_noon = last_wed.replace(hour=12, minute=0, second=0, microsecond=0)

    if ref_local < last_wed_noon:
        last_wed_noon -= timedelta(days=7)

    # Convert bounds to UTC for consistent SQLite comparison
    lower = last_wed_noon.astimezone(UTC)
    upper = (last_wed_noon + timedelta(days=7)).astimezone(UTC)

    return s.scalars(
        select(Event).where(
            Event.When >= lower,
            Event.When < upper,
        )
    ).all()


def get_random_previous_location(s: Session) -> Location | None:
    """Select a random location from past events.

    Only open, legal locations that have previously hosted an event are
    considered.  Uses a single JOIN query to avoid N+1.

    :param s: Active database session.
    :returns: A randomly chosen eligible location, or ``None`` if no eligible
        locations exist.
    :rtype: Location | None
    """
    from random import choice

    open_locations = s.scalars(
        select(Location)
        .join(Event, Location.id == Event.LocationID)
        .where(Location.Closed == False, Location.Illegal == False)  # noqa: E712
        .distinct()
    ).all()

    if not open_locations:
        return None

    return choice(open_locations)


def get_accounts_with_claim(s: Session, claim: AccountClaims) -> list[Account]:
    """Get all accounts that have a specific claim set in their bitmask.

    Uses a SQL bitwise filter to avoid loading all accounts.

    :param s: Active database session.
    :param claim: The claim flag to test for.
    :returns: A list of accounts whose claims include *claim*.
    :rtype: list[Account]
    """
    claim_val = literal(claim.value)
    return s.scalars(
        select(Account).where(
            Account.claims.bitwise_and(claim_val) == claim_val
        )
    ).all()


# --- Tyrant Rotation functions ---

def create_tyrant_assignment(
    s: Session,
    account_id: int,
    cycle: int,
    position: int,
    assigned_at: datetime,
    deadline_at: datetime | None = None,
    status: TyrantAssignmentStatus = TyrantAssignmentStatus.SCHEDULED,
) -> TyrantRotation:
    """Create and persist a new tyrant rotation assignment.

    :param s: Active database session.
    :param account_id: ID of the account being assigned.
    :param cycle: Rotation cycle number.
    :param position: Position within the cycle (0-based).
    :param assigned_at: Datetime when the assignment was made.
    :param deadline_at: Datetime by which the tyrant must choose a location,
        or ``None`` for future SCHEDULED assignments.
    :param status: Initial status (default :attr:`SCHEDULED`).
    :returns: The newly created and committed rotation assignment.
    :rtype: TyrantRotation
    """
    rotation = TyrantRotation(
        account_id=account_id,
        cycle=cycle,
        position=position,
        assigned_at=assigned_at,
        deadline_at=deadline_at,
        status=status,
    )
    s.add(rotation)
    s.flush()
    return rotation


def create_cycle_rotation(
    s: Session,
    admins: list[Account],
    cycle: int,
    now: datetime,
) -> list[TyrantRotation]:
    """Create the entire rotation for a new cycle with shuffled order.

    All assignments start as :attr:`~TyrantAssignmentStatus.SCHEDULED`
    with no deadline set.  The caller is responsible for activating
    the first assignment.

    :param s: Active database session.
    :param admins: The list of accounts to include.  The list is shuffled
        in-place to determine the cycle order.
    :param cycle: The cycle number to assign.
    :param now: Reference datetime used as ``assigned_at``.
    :returns: The list of newly created rotation assignments in position
        order.
    :rtype: list[TyrantRotation]
    """
    from random import shuffle

    shuffle(admins)
    rotations: list[TyrantRotation] = []
    for position, admin in enumerate(admins):
        rotation = TyrantRotation(
            account_id=admin.id,
            cycle=cycle,
            position=position,
            assigned_at=now,
            deadline_at=None,
            status=TyrantAssignmentStatus.SCHEDULED,
        )
        s.add(rotation)
        rotations.append(rotation)
    s.flush()
    return rotations


def get_current_pending_assignment(s: Session) -> TyrantRotation | None:
    """Get the most recent tyrant rotation assignment with PENDING status.

    :param s: Active database session.
    :returns: The current pending assignment, or ``None`` if there is none.
    :rtype: TyrantRotation | None
    """
    return s.scalars(
        select(TyrantRotation)
        .where(TyrantRotation.status == TyrantAssignmentStatus.PENDING)
        .order_by(TyrantRotation.assigned_at.desc())
    ).first()


def get_next_scheduled_assignment(s: Session, cycle: int) -> TyrantRotation | None:
    """Get the next SCHEDULED assignment in a cycle, ordered by position.

    :param s: Active database session.
    :param cycle: The cycle number to search within.
    :returns: The next scheduled assignment, or ``None`` if the cycle has
        no remaining scheduled assignments.
    :rtype: TyrantRotation | None
    """
    return s.scalars(
        select(TyrantRotation)
        .where(
            TyrantRotation.cycle == cycle,
            TyrantRotation.status == TyrantAssignmentStatus.SCHEDULED,
        )
        .order_by(TyrantRotation.position.asc())
    ).first()


def get_on_deck_assignment(s: Session, cycle: int, current_position: int) -> TyrantRotation | None:
    """Get the next SCHEDULED assignment after the given position.

    Used to find the "on deck" person who will be assigned next week.

    :param s: Active database session.
    :param cycle: The cycle number to search within.
    :param current_position: The position of the current assignment.
    :returns: The next scheduled assignment after *current_position*,
        or ``None`` if no more remain.
    :rtype: TyrantRotation | None
    """
    return s.scalars(
        select(TyrantRotation)
        .where(
            TyrantRotation.cycle == cycle,
            TyrantRotation.status == TyrantAssignmentStatus.SCHEDULED,
            TyrantRotation.position > current_position,
        )
        .order_by(TyrantRotation.position.asc())
    ).first()


def activate_assignment(
    s: Session,
    assignment_id: int,
    deadline_at: datetime,
) -> None:
    """Activate a SCHEDULED assignment by setting it to PENDING with a deadline.

    :param s: Active database session.
    :param assignment_id: The assignment's integer ID.
    :param deadline_at: Datetime by which the tyrant must choose a location.
    """
    rotation = s.scalars(
        select(TyrantRotation).where(TyrantRotation.id == assignment_id)
    ).first()
    if rotation is not None:
        rotation.status = TyrantAssignmentStatus.PENDING
        rotation.deadline_at = deadline_at
        s.flush()


def get_rotation_schedule(s: Session, cycle: int) -> list[TyrantRotation]:
    """Get the full rotation schedule for a cycle, ordered by position.

    :param s: Active database session.
    :param cycle: The cycle number to retrieve.
    :returns: A list of all assignments in the cycle, ordered by position.
    :rtype: list[TyrantRotation]
    """
    return s.scalars(
        select(TyrantRotation)
        .options(joinedload(TyrantRotation.Account))
        .where(TyrantRotation.cycle == cycle)
        .order_by(TyrantRotation.position.asc())
    ).all()


def get_current_cycle_number(s: Session) -> int:
    """Get the current (maximum) rotation cycle number.

    :param s: Active database session.
    :returns: The highest cycle number, defaulting to ``1`` if no assignments
        exist.
    :rtype: int
    """
    row = s.execute(select(func.max(TyrantRotation.cycle))).scalar()
    if row is None:
        return 1
    return row


def get_consecutive_misses(s: Session, account_id: int) -> int:
    """Count the most recent unbroken streak of MISSED assignments for an account.

    :param s: Active database session.
    :param account_id: The account ID to check.
    :returns: Number of consecutive MISSED assignments starting from the most
        recent.
    :rtype: int
    """
    rotations = s.scalars(
        select(TyrantRotation)
        .where(TyrantRotation.account_id == account_id)
        .order_by(TyrantRotation.assigned_at.desc())
    ).all()

    count = 0
    for rotation in rotations:
        if rotation.status == TyrantAssignmentStatus.MISSED:
            count += 1
        else:
            break
    return count


def _update_assignment_status(s: Session, assignment_id: int, status: TyrantAssignmentStatus) -> None:
    """Update a tyrant rotation assignment's status.

    :param s: Active database session.
    :param assignment_id: The assignment's integer ID.
    :param status: The new status to set.
    """
    rotation = s.scalars(
        select(TyrantRotation).where(TyrantRotation.id == assignment_id)
    ).first()
    if rotation is not None:
        rotation.status = status
        s.flush()


def mark_assignment_chosen(s: Session, assignment_id: int) -> None:
    """Mark a tyrant rotation assignment as CHOSEN.

    :param s: Active database session.
    :param assignment_id: The assignment's integer ID.
    """
    _update_assignment_status(s, assignment_id, TyrantAssignmentStatus.CHOSEN)


def mark_assignment_missed(s: Session, assignment_id: int) -> None:
    """Mark a tyrant rotation assignment as MISSED.

    :param s: Active database session.
    :param assignment_id: The assignment's integer ID.
    """
    _update_assignment_status(s, assignment_id, TyrantAssignmentStatus.MISSED)


def remove_claim_from_account(s: Session, account_id: int, claim: AccountClaims) -> None:
    """Remove a specific claim from an account's bitmask.

    :param s: Active database session.
    :param account_id: The account's integer ID.
    :param claim: The claim flag to remove.
    """
    account = s.scalars(select(Account).where(Account.id == account_id)).first()
    if account is not None:
        account.claims = account.claims & ~claim
        s.flush()


def update_account_claims(s: Session, account_id: int, new_claims: AccountClaims) -> None:
    """Set an account's claims to a new bitmask value.

    :param s: Active database session.
    :param account_id: The account's integer ID.
    :param new_claims: The replacement claims bitmask.
    """
    account = s.scalars(select(Account).where(Account.id == account_id)).first()
    if account is not None:
        account.claims = new_claims
        s.flush()
