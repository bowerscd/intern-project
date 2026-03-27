"""
Happy Hour event and rotation endpoints — authenticated, require HAPPY_HOUR claim.
Event creation is restricted to HAPPY_HOUR_TYRANT users, and only the
currently assigned tyrant may create during their rotation window.
If no assignment is pending, any HAPPY_HOUR user may create.
"""

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError

from routes.shared import Database, RequireLogin, require_write_access
from models import AccountClaims
from csrf import validate_csrf_token

from schemas.happyhour import (
    EventCreate,
    EventUpdate,
    EventResponse,
    PaginatedEventResponse,
    RotationMemberResponse,
    RotationScheduleResponse,
)

from .router import HappyHour

logger = logging.getLogger(__name__)


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
            logger.warning("Event #%d not found", event_id)
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
        # Require HAPPY_HOUR_TYRANT to create events
        if not (
            account.claims & AccountClaims.HAPPY_HOUR_TYRANT
            == AccountClaims.HAPPY_HOUR_TYRANT
        ):
            logger.warning(
                "Event create denied: account #%d lacks HAPPY_HOUR_TYRANT",
                account.id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only HAPPY_HOUR_TYRANT users may create events",
            )

        # Any tyrant can submit for a FUTURE week.  For the CURRENT week
        # (the week the pending person is responsible for), only the pending
        # person or an ADMIN may create.
        pending = get_current_pending_assignment(db)

        from datetime import datetime, UTC

        when_ref = body.when if body.when else datetime.now(UTC)

        if pending is not None:
            from db.functions import _compute_week_of

            now = datetime.now(UTC)
            pending_week = _compute_week_of(now)
            event_week = _compute_week_of(when_ref)

            if event_week == pending_week and pending.account_id != account.id:
                is_admin = account.claims & AccountClaims.ADMIN == AccountClaims.ADMIN
                if not is_admin:
                    logger.warning(
                        "Event create denied: account #%d is not the assigned "
                        "tyrant (#%d) for the current week",
                        account.id,
                        pending.account_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="It's not your turn to pick the happy hour location",
                    )
        existing = get_events_this_week(db, when_ref)
        if existing:
            logger.info(
                "Event create: duplicate for week of %s by account #%d",
                when_ref.isoformat(),
                account.id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A happy hour event already exists for this week",
            )

        # Verify location exists
        location = get_location_by_id(db, body.location_id)
        if location is None:
            logger.warning("Event create: location #%d not found", body.location_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found",
            )

        if location.Closed:
            logger.warning("Event create: location #%d is closed", body.location_id)
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
            logger.info(
                "Event create: integrity error (duplicate week) by account #%d",
                account.id,
            )
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
        logger.exception("Failed to send event notifications")

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


@HappyHour.patch(
    "/events/{event_id}",
    summary="Update a happy hour event",
    dependencies=[Depends(validate_csrf_token)],
    description="Update an existing happy hour event (change location, time, or "
    "description). Requires HAPPY_HOUR_TYRANT or ADMIN claim. Use when the wrong "
    "venue or time was chosen. Sends updated notifications to all HAPPY_HOUR users.",
    response_model=EventResponse,
)
async def update_event_endpoint(
    event_id: int,
    body: EventUpdate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> EventResponse:
    """Update an existing happy hour event for disaster recovery.

    Allows changing the location, time, or description after the event
    was created.  If the location is changed, the new location must be
    open.  Sends updated notifications to all HAPPY_HOUR users.

    Requires ``HAPPY_HOUR_TYRANT`` or ``ADMIN`` claim.

    :param event_id: The event's integer ID.
    :param body: The event update payload.
    :param account: The authenticated account.
    :param db: Active database session.
    :returns: The updated :class:`EventResponse`.
    :raises HTTPException: If the event or new location is not found,
        or the new location is closed.
    """
    require_write_access(account)

    is_tyrant = (
        account.claims & AccountClaims.HAPPY_HOUR_TYRANT
    ) == AccountClaims.HAPPY_HOUR_TYRANT
    is_admin = (account.claims & AccountClaims.ADMIN) == AccountClaims.ADMIN
    if not (is_tyrant or is_admin):
        logger.warning(
            "Event update denied: account #%d lacks HAPPY_HOUR_TYRANT or ADMIN",
            account.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires HAPPY_HOUR_TYRANT or ADMIN permission",
        )

    from db.functions import (
        update_event_fields,
        get_location_by_id,
        get_event_by_id,
    )

    with db:
        event = get_event_by_id(db, event_id)
        if event is None:
            logger.warning("Event update: event #%d not found", event_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found",
            )

        # Validate new location if provided
        if body.location_id is not None:
            location = get_location_by_id(db, body.location_id)
            if location is None:
                logger.warning("Event update: location #%d not found", body.location_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Location not found",
                )
            if location.Closed:
                logger.warning("Event update: location #%d is closed", body.location_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Location is closed",
                )

        update_kwargs: dict = {}
        if body.location_id is not None:
            update_kwargs["location_id"] = body.location_id
        if body.when is not None:
            update_kwargs["when"] = body.when
        if body.description is not None:
            update_kwargs["description"] = body.description

        try:
            updated = update_event_fields(db, event_id, **update_kwargs)
        except IntegrityError:
            db.rollback()
            logger.info(
                "Event update: integrity error (duplicate week) for event #%d",
                event_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another event already exists for the target week",
            )

        if updated is None:
            logger.warning("Event update: event #%d disappeared mid-update", event_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found",
            )

        db.commit()
        response = _event_response(updated)
        saved_event_id = updated.id

    # Re-notify all HAPPY_HOUR users about the change
    try:
        from mail.outgoing import notify_happy_hour_updated

        with db:
            from db.functions import get_event_by_id as _get_event

            fresh_event = _get_event(db, saved_event_id)
            if fresh_event is not None:
                await notify_happy_hour_updated(fresh_event, db)
    except Exception:
        logger.exception("Failed to send event update notifications")

    return response


@HappyHour.delete(
    "/events/{event_id}",
    summary="Cancel a happy hour event",
    dependencies=[Depends(validate_csrf_token)],
    description="Cancel (delete) a happy hour event. Frees the weekly slot so a "
    "replacement event can be created. Requires HAPPY_HOUR_TYRANT or ADMIN claim. "
    "Sends cancellation notifications to all HAPPY_HOUR users.",
    status_code=status.HTTP_200_OK,
)
async def cancel_event_endpoint(
    event_id: int,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> dict:
    """Cancel a happy hour event.

    Deletes the event and frees the ``week_of`` unique constraint,
    allowing a new event to be created for the same week.

    Requires ``HAPPY_HOUR_TYRANT`` or ``ADMIN`` claim.

    :param event_id: The event's integer ID.
    :param account: The authenticated account.
    :param db: Active database session.
    :returns: A status dict with details about the cancelled event.
    :raises HTTPException: If the event is not found.
    """
    require_write_access(account)

    is_tyrant = (
        account.claims & AccountClaims.HAPPY_HOUR_TYRANT
    ) == AccountClaims.HAPPY_HOUR_TYRANT
    is_admin = (account.claims & AccountClaims.ADMIN) == AccountClaims.ADMIN
    if not (is_tyrant or is_admin):
        logger.warning(
            "Event cancel denied: account #%d lacks HAPPY_HOUR_TYRANT or ADMIN",
            account.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires HAPPY_HOUR_TYRANT or ADMIN permission",
        )

    from db.functions import get_event_by_id, delete_event

    with db:
        event = get_event_by_id(db, event_id)
        if event is None:
            logger.warning("Event cancel: event #%d not found", event_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found",
            )

        # Capture event info for the notification before deleting
        event_info = {
            "location_name": event.Location.Name,
            "location_address": event.Location.AddressRaw,
            "when": event.When,
        }

        delete_event(db, event_id)
        db.commit()

    # Notify all HAPPY_HOUR users about the cancellation
    try:
        from mail.outgoing import notify_happy_hour_cancelled

        with db:
            await notify_happy_hour_cancelled(event_info, db)
    except Exception:
        logger.exception("Failed to send event cancellation notifications")

    return {"status": "cancelled", "event_id": event_id}


@HappyHour.post(
    "/rotation/skip",
    summary="Skip the current rotation turn",
    dependencies=[Depends(validate_csrf_token)],
    description="Voluntarily skip the current rotation turn. Marks the assignment "
    "as SKIPPED (does not count toward the consecutive miss limit) and "
    "activates the next person in the rotation. Requires HAPPY_HOUR_TYRANT "
    "(own turn) or ADMIN (any turn).",
    status_code=status.HTTP_200_OK,
)
async def skip_rotation_turn(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> dict:
    """Voluntarily skip the current tyrant's rotation turn.

    The assignment is marked as SKIPPED (not MISSED), so it does not
    count toward the consecutive miss limit.  The next person in the
    rotation is activated with a new deadline.

    Requires ``HAPPY_HOUR_TYRANT`` (own turn only) or ``ADMIN`` (any turn).

    :param account: The authenticated account.
    :param db: Active database session.
    :returns: A status dict indicating who was skipped and who is next.
    :raises HTTPException: If no pending assignment exists or it's not
        the caller's turn.
    """
    require_write_access(account)

    is_tyrant = (
        account.claims & AccountClaims.HAPPY_HOUR_TYRANT
    ) == AccountClaims.HAPPY_HOUR_TYRANT
    is_admin = (account.claims & AccountClaims.ADMIN) == AccountClaims.ADMIN
    if not (is_tyrant or is_admin):
        logger.warning(
            "Rotation skip denied: account #%d lacks HAPPY_HOUR_TYRANT or ADMIN",
            account.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires HAPPY_HOUR_TYRANT or ADMIN permission",
        )

    from db.functions import (
        get_current_pending_assignment,
        skip_assignment,
        get_next_scheduled_assignment,
        activate_assignment,
        get_current_cycle_number,
    )

    # Capture values before the session closes (lesson #034)
    account_id = account.id
    account_username = account.username

    with db:
        pending = get_current_pending_assignment(db)
        if pending is None:
            logger.warning(
                "Rotation skip: no pending assignment (account #%d)", account_id
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending rotation assignment to skip",
            )

        # ADMIN can skip anyone's turn; TYRANT can only skip their own
        if not is_admin and pending.account_id != account_id:
            logger.warning(
                "Rotation skip denied: account #%d tried to skip #%d's turn",
                account_id,
                pending.account_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only skip your own rotation turn",
            )

        skip_assignment(db, pending.id)

        # Activate the next person in the rotation
        cycle = get_current_cycle_number(db)
        next_up = get_next_scheduled_assignment(db, cycle)
        next_username = None
        next_up_id = None

        if next_up is not None:
            from datetime import datetime, UTC
            from scheduler import _next_wednesday_noon

            now = datetime.now(UTC)
            deadline = _next_wednesday_noon(now)
            activate_assignment(db, next_up.id, deadline)
            db.refresh(next_up)
            next_username = next_up.Account.username
            next_up_id = next_up.id

        db.commit()

    # Notify the next person if one was activated
    if next_up_id is not None and next_username is not None:
        try:
            from mail.outgoing import notify_tyrant_assigned

            with db:
                from db.functions import get_assignment_by_id

                fresh_next = get_assignment_by_id(db, next_up_id)
                if fresh_next is not None:
                    await notify_tyrant_assigned(
                        fresh_next.Account, fresh_next.deadline_at
                    )
        except Exception:
            logger.exception("Failed to notify next tyrant after skip")

    return {
        "status": "skipped",
        "skipped_user": account_username,
        "next_user": next_username,
    }
