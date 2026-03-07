"""
Happy Hour event and rotation endpoints — authenticated, require HAPPY_HOUR claim.
Event creation is restricted to HAPPY_HOUR_TYRANT users, and only the
currently assigned tyrant may create during their rotation window.
If no assignment is pending, any HAPPY_HOUR user may create.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError

from routes.shared import Database, RequireLogin, require_write_access
from models import AccountClaims
from csrf import validate_csrf_token

from schemas.happyhour import (
    EventCreate,
    EventResponse,
    PaginatedEventResponse,
    RotationMemberResponse,
    RotationScheduleResponse,
)

from .router import HappyHour


def _event_response(event: Any, current_tyrant: Any = None) -> EventResponse:
    """Build an :class:`EventResponse` from a database event entity.

    :param event: The database :class:`Event` entity.
    :param current_tyrant: The current pending tyrant rotation
        assignment, or ``None``.
    :returns: A populated :class:`EventResponse`.
    :rtype: EventResponse
    """
    return EventResponse(
        id=event.id,
        description=event.Description,
        when=event.When,
        location_id=event.LocationID,
        location_name=event.Location.Name,
        location_url=event.Location.URL,
        location_address=event.Location.AddressRaw,
        tyrant_username=event.Tyrant.username if event.Tyrant else None,
        auto_selected=event.AutoSelected,
        current_tyrant_username=(
            current_tyrant.Account.username if current_tyrant else None
        ),
        current_tyrant_deadline=(
            current_tyrant.deadline_at if current_tyrant else None
        ),
    )


@HappyHour.get(
    "/events",
    summary="List all happy hour events",
    description="Get the history of all happy hour events with pagination. Requires HAPPY_HOUR claim.",
    response_model=PaginatedEventResponse,
)
async def list_events(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> PaginatedEventResponse:
    """Return a paginated list of happy hour events, newest first.

    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :param page: Page number (1-based).
    :param page_size: Maximum number of items per page (1-100).
    :returns: A :class:`PaginatedEventResponse` with the requested page.
    :rtype: PaginatedEventResponse
    """
    from db.functions import get_events_paginated, count_events

    with db:
        total = count_events(db)
        offset = (page - 1) * page_size
        events = get_events_paginated(db, offset, page_size)

        return PaginatedEventResponse(
            items=[_event_response(e) for e in events],
            total=total,
            page=page,
            page_size=page_size,
        )


@HappyHour.get(
    "/events/upcoming",
    summary="Get the next upcoming happy hour event",
    description="Get the next scheduled happy hour event. Requires HAPPY_HOUR claim.",
    response_model=EventResponse | None,
)
async def upcoming_event(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> EventResponse | None:
    """Return the next upcoming happy hour event.

    If no event exists but a tyrant is assigned, returns a placeholder
    response with the tyrant's deadline.

    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :returns: An :class:`EventResponse`, or ``None`` if nothing is
        scheduled and no tyrant is assigned.
    :rtype: EventResponse | None
    """
    from db.functions import get_upcoming_event, get_current_pending_assignment

    with db:
        event = get_upcoming_event(db)
        pending = get_current_pending_assignment(db)

        if event is None:
            if pending is None:
                return None
            # No upcoming event but there is a pending tyrant assignment
            return EventResponse(
                id=0,
                description=None,
                when=pending.deadline_at,
                location_id=0,
                location_name="",
                tyrant_username=None,
                auto_selected=False,
                current_tyrant_username=pending.Account.username,
                current_tyrant_deadline=pending.deadline_at,
            )

        return _event_response(event, current_tyrant=pending)


@HappyHour.get(
    "/events/{event_id}",
    summary="Get a specific happy hour event",
    description="Get details of a happy hour event by ID. Requires HAPPY_HOUR claim.",
    response_model=EventResponse,
)
async def get_event(
    event_id: int,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> EventResponse:
    """Return a specific happy hour event by ID.

    :param event_id: The event's integer ID.
    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :returns: The matching :class:`EventResponse`.
    :rtype: EventResponse
    :raises HTTPException: If the event is not found.
    """
    from db.functions import get_event_by_id

    with db:
        event = get_event_by_id(db, event_id)

        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found",
            )

        return _event_response(event)


@HappyHour.post(
    "/events",
    summary="Schedule a new happy hour event",
    dependencies=[Depends(validate_csrf_token)],
    description="Schedule a new happy hour event. Only the currently assigned tyrant "
    "(HAPPY_HOUR_TYRANT) may create during a rotation window. If no assignment "
    "is pending, any HAPPY_HOUR user may create. Automatically sends email "
    "and SMS notifications to all users with HAPPY_HOUR permissions.",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_event_endpoint(
    body: EventCreate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> EventResponse:
    """Schedule a new happy hour event.

    Only the currently assigned tyrant may create during a rotation
    window.  Automatically sends notifications to all users with the
    ``HAPPY_HOUR`` claim.

    :param body: The event creation payload.
    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :returns: The newly created :class:`EventResponse`.
    :rtype: EventResponse
    :raises HTTPException: If the user is not the assigned tyrant, the
        location is not found, or the location is closed.
    """
    require_write_access(account)

    from db.functions import (
        create_event,
        get_location_by_id,
        get_current_pending_assignment,
        mark_assignment_chosen,
        get_events_this_week,
    )

    with db:
        # Check rotation enforcement
        pending = get_current_pending_assignment(db)

        if pending is not None:
            # There is an active rotation assignment — only the assigned tyrant may submit
            if not (
                account.claims & AccountClaims.HAPPY_HOUR_TYRANT
                == AccountClaims.HAPPY_HOUR_TYRANT
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only HAPPY_HOUR_TYRANT users may create events during a rotation window",
                )
            if pending.account_id != account.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="It's not your turn to pick the happy hour location",
                )
        else:
            # No pending assignment — any HAPPY_HOUR_TYRANT user may submit
            if not (
                account.claims & AccountClaims.HAPPY_HOUR_TYRANT
                == AccountClaims.HAPPY_HOUR_TYRANT
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You need the HAPPY_HOUR_TYRANT permission to submit happy hour events",
                )

        # Guard against duplicate events in the same weekly window as the proposed event
        from datetime import datetime, UTC

        when_ref = body.when if body.when else datetime.now(UTC)
        existing = get_events_this_week(db, when_ref)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A happy hour event already exists for this week",
            )

        # Verify location exists
        location = get_location_by_id(db, body.location_id)
        if location is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found",
            )

        if location.Closed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Location is closed",
            )

        try:
            event = create_event(
                db,
                location_id=body.location_id,
                tyrant_id=account.id,
                when=body.when,
                description=body.description,
            )
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A happy hour event already exists for this week",
            )

        # Mark the rotation assignment as chosen if applicable
        if pending is not None and pending.account_id == account.id:
            mark_assignment_chosen(db, pending.id)

        db.commit()
        response = _event_response(event)
        event_id = event.id

    # Send notifications outside the DB transaction using a fresh session
    try:
        from mail.outgoing import notify_happy_hour_users

        with db:
            from db.functions import get_event_by_id

            fresh_event = get_event_by_id(db, event_id)
            if fresh_event is not None:
                await notify_happy_hour_users(fresh_event, db)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to send event notifications")

    return response


@HappyHour.get(
    "/rotation",
    summary="Get the current rotation schedule",
    description="Get the full tyrant rotation schedule for the current cycle. "
    "Requires HAPPY_HOUR claim.",
    response_model=RotationScheduleResponse,
)
async def get_rotation(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> RotationScheduleResponse:
    """Return the full rotation schedule for the current cycle.

    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :returns: A :class:`RotationScheduleResponse` with the ordered member
        list.
    :rtype: RotationScheduleResponse
    """
    from db.functions import (
        get_current_cycle_number,
        get_rotation_schedule,
        get_accounts_with_claim,
        create_cycle_rotation,
        activate_assignment,
        get_next_scheduled_assignment,
    )

    with db:
        cycle = get_current_cycle_number(db)
        schedule = get_rotation_schedule(db, cycle)

        # Auto-seed the rotation if no schedule exists and there are
        # eligible HAPPY_HOUR_TYRANT users
        if not schedule:
            tyrants = get_accounts_with_claim(db, AccountClaims.HAPPY_HOUR_TYRANT)
            if tyrants:
                from datetime import datetime, timedelta, UTC

                now = datetime.now(UTC)
                new_cycle = cycle + 1
                create_cycle_rotation(db, tyrants, new_cycle, now)
                # Activate the first person — deadline is next Wednesday noon PST
                next_up = get_next_scheduled_assignment(db, new_cycle)
                if next_up:
                    # Next Wednesday at noon PST (UTC-8) = 20:00 UTC
                    days_until_wed = (2 - now.weekday() + 7) % 7 or 7
                    deadline = now.replace(
                        hour=20, minute=0, second=0, microsecond=0
                    ) + timedelta(days=days_until_wed)
                    activate_assignment(db, next_up.id, deadline)
                db.commit()
                cycle = new_cycle
                schedule = get_rotation_schedule(db, cycle)

        members = [
            RotationMemberResponse(
                position=r.position,
                username=r.Account.username,
                status=r.status.value,
                deadline=r.deadline_at,
            )
            for r in schedule
        ]

        return RotationScheduleResponse(cycle=cycle, members=members)
