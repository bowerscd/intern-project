"""
Legacy v1 API endpoints — backwards compatible with special-tribble.

.. deprecated::
    These endpoints are **permanently disabled** and always return
    ``410 Gone``.  The code is retained for historical reference only.
    Use the v2 API instead.
"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status, Query

from routes.tags import ApiTags
from routes.shared import (
    Database,
    reject_if_legacy_disabled,
    mark_legacy_routes_deprecated,
)

from schemas.mealbot import (
    AccountModificationRequest,
    CreateRecordRequest,
    RecordResponse,
)


MealbotV1 = APIRouter(
    prefix="/v1",
    tags=[ApiTags.Mealbot],
)


@MealbotV1.post(
    "/User",
    summary="Create a new user",
    description="Create a new mealbot user account. Only the CREATE operation is supported.",
    status_code=status.HTTP_200_OK,
)
@reject_if_legacy_disabled
async def create_user(body: AccountModificationRequest, db: Database) -> dict[str, str]:
    """Create a new mealbot user account.

    :param body: The account creation payload.
    :param db: Active database session.
    :returns: A status dict.
    :rtype: dict[str, str]
    :raises HTTPException: If the user already exists.
    """
    from db.functions import get_account_by_username, create_account
    from models import ExternalAuthProvider

    with db:
        existing = get_account_by_username(db, body.user)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User '{body.user}' already exists",
            )

        try:
            account = create_account(
                username=body.user,
                email=None,
                account_provider=ExternalAuthProvider.test,
                external_unique_id=body.user,
            )
            db.add(account)
            db.commit()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )

    return {"status": "ok"}


@MealbotV1.get(
    "/Summary",
    summary="Get record summary",
    description="Get a summary of meal credits. Optionally filter by user and/or time range.",
)
@reject_if_legacy_disabled
async def get_summary(
    db: Database,
    user: Optional[str] = Query(None, description="Filter by username"),
    start: Optional[datetime] = Query(
        None, description="Start of time range (ISO 8601)"
    ),
    end: Optional[datetime] = Query(None, description="End of time range (ISO 8601)"),
) -> dict[str, Any]:
    """Return a credit summary, optionally filtered by user and time range.

    :param db: Active database session.
    :param user: Username to filter by, or ``None`` for global summary.
    :param start: Inclusive lower time bound, or ``None``.
    :param end: Inclusive upper time bound, or ``None``.
    :returns: A dict representing the credit summary.
    :rtype: dict[str, Any]
    """
    from routes.shared import resolve_summary

    with db:
        return resolve_summary(db, user, start, end)


@MealbotV1.get(
    "/Record",
    summary="Get meal records",
    description="Get meal records. Optionally filter by users, limit, and/or time range.",
    response_model=list[RecordResponse],
)
@reject_if_legacy_disabled
async def get_records(
    db: Database,
    user1: Optional[str] = Query(None, description="First user to filter by"),
    user2: Optional[str] = Query(None, description="Second user (requires user1)"),
    limit: Optional[int] = Query(
        None, description="Maximum number of records to return", gt=0
    ),
    start: Optional[datetime] = Query(
        None, description="Start of time range (ISO 8601)"
    ),
    end: Optional[datetime] = Query(None, description="End of time range (ISO 8601)"),
) -> list[RecordResponse]:
    """Return meal records, with optional filtering by users, limit, and time.

    :param db: Active database session.
    :param user1: First username filter, or ``None``.
    :param user2: Second username filter (requires *user1*), or ``None``.
    :param limit: Maximum number of records, or ``None`` for all.
    :param start: Inclusive lower time bound, or ``None``.
    :param end: Inclusive upper time bound, or ``None``.
    :returns: A list of :class:`RecordResponse` objects.
    :rtype: list[RecordResponse]
    :raises HTTPException: If ``user2`` is given without ``user1``, or
        only one of ``start``/``end`` is provided.
    """
    from db.functions import (
        get_all_records,
        get_records_with_limit,
        get_records_for_user,
        get_records_between_users,
        get_timebound_records,
        get_timebound_records_for_user,
        get_timebound_records_between_users,
    )

    # Validate: user2 requires user1
    if user2 is not None and user1 is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user2 requires user1",
        )

    # Validate: start and end must both be present or both absent
    if (start is None) != (end is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start and end must both be provided or both omitted",
        )

    with db:
        try:
            has_timebound = start is not None and end is not None

            if user1 is not None and user2 is not None:
                if has_timebound:
                    receipts = get_timebound_records_between_users(
                        db, user1, user2, start, end, limit
                    )
                else:
                    receipts = get_records_between_users(db, user1, user2, limit)
            elif user1 is not None:
                if has_timebound:
                    receipts = get_timebound_records_for_user(
                        db, user1, start, end, limit
                    )
                else:
                    receipts = get_records_for_user(db, user1, limit)
            else:
                if has_timebound:
                    receipts = get_timebound_records(db, start, end, limit)
                elif limit is not None:
                    receipts = get_records_with_limit(db, limit)
                else:
                    receipts = get_all_records(db)

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        return [RecordResponse.from_receipt(r) for r in receipts]


@MealbotV1.post(
    "/Record",
    summary="Create a meal record",
    description="Create a new meal credit record between two users.",
    status_code=status.HTTP_200_OK,
)
@reject_if_legacy_disabled
async def create_record(body: CreateRecordRequest, db: Database) -> dict[str, str]:
    """Create a new meal credit record.

    :param body: The record creation payload.
    :param db: Active database session.
    :returns: A status dict.
    :rtype: dict[str, str]
    :raises HTTPException: If the payer and recipient are the same or
        either does not exist.
    """
    from db.functions import create_receipt

    if body.payer == body.recipient:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payer and recipient cannot be the same person",
        )

    with db:
        try:
            create_receipt(db, body.payer, body.recipient, body.credits)
            db.commit()
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    return {"status": "ok"}


mark_legacy_routes_deprecated(MealbotV1)
