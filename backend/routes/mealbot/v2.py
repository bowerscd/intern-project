"""
v2 Mealbot API endpoints — authenticated.
Requires MEALBOT claim for most operations.
"""
from typing import Annotated, Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query

from routes.tags import ApiTags
from routes.shared import Database, RequireLogin
from csrf import validate_csrf_token

from models import AccountClaims

from schemas.mealbot import (
    RecordResponse,
    PaginatedRecordResponse,
    CreateRecordRequest,
)

MealbotV2 = APIRouter(
    prefix="/v2/mealbot",
    tags=[ApiTags.Mealbot],
)


@MealbotV2.get(
    "/ledger",
    summary="Get full meal ledger",
    description="Get all meal records with pagination. Requires MEALBOT claim.",
    response_model=PaginatedRecordResponse,
)
async def ledger(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.MEALBOT))],
    db: Database,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> PaginatedRecordResponse:
    """Return a paginated meal ledger.

    :param account: The authenticated account with ``MEALBOT`` claim.
    :param db: Active database session.
    :param page: Page number (1-based).
    :param page_size: Maximum number of items per page (1-100).
    :returns: A :class:`PaginatedRecordResponse` with the requested page.
    :rtype: PaginatedRecordResponse
    """
    from db.functions import get_records_paginated, count_records

    with db:
        total = count_records(db)
        offset = (page - 1) * page_size
        receipts = get_records_paginated(db, offset, page_size)

        return PaginatedRecordResponse(
            items=[RecordResponse.from_receipt(r) for r in receipts],
            total=total,
            page=page,
            page_size=page_size,
        )


@MealbotV2.get(
    "/ledger/me",
    summary="Get personal meal ledger",
    description="Get meal records for the authenticated user with pagination. Requires MEALBOT claim.",
    response_model=PaginatedRecordResponse,
)
async def my_ledger(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.MEALBOT))],
    db: Database,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> PaginatedRecordResponse:
    """Return a paginated personal meal ledger for the authenticated user.

    :param account: The authenticated account with ``MEALBOT`` claim.
    :param db: Active database session.
    :param page: Page number (1-based).
    :param page_size: Maximum number of items per page (1-100).
    :returns: A :class:`PaginatedRecordResponse` with the requested page.
    :rtype: PaginatedRecordResponse
    """
    from db.functions import get_records_for_user_paginated, count_records_for_user

    with db:
        total = count_records_for_user(db, account.username)
        offset = (page - 1) * page_size
        receipts = get_records_for_user_paginated(db, account.username, offset, page_size)

        return PaginatedRecordResponse(
            items=[RecordResponse.from_receipt(r) for r in receipts],
            total=total,
            page=page,
            page_size=page_size,
        )


@MealbotV2.get(
    "/summary",
    summary="Get meal summary",
    description="Get a summary of meal credits for the authenticated user or global. Requires MEALBOT claim.",
)
async def summary(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.MEALBOT))],
    db: Database,
    user: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
) -> dict[str, Any]:
    """Return a credit summary for the authenticated user or global.

    :param account: The authenticated account with ``MEALBOT`` claim.
    :param db: Active database session.
    :param user: Username to filter by, or ``None``.
    :param start: Inclusive lower time bound, or ``None``.
    :param end: Inclusive upper time bound, or ``None``.
    :returns: A dict representing the credit summary.
    :rtype: dict[str, Any]
    """
    from routes.shared import resolve_summary

    with db:
        return resolve_summary(db, user, start, end)


@MealbotV2.post(
    "/record",
    summary="Create a meal record",
    dependencies=[Depends(validate_csrf_token)],
    description="Create a new meal credit record. Requires MEALBOT claim.",
    status_code=status.HTTP_200_OK,
)
async def record(
    body: CreateRecordRequest,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.MEALBOT))],
    db: Database,
) -> dict[str, str]:
    """Create a new meal credit record.

    :param body: The record creation payload.
    :param account: The authenticated account with ``MEALBOT`` claim.
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

    if account.username not in (body.payer, body.recipient):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be either the payer or the recipient",
        )

    with db:
        try:
            create_receipt(
                db,
                body.payer,
                body.recipient,
                body.credits,
                recorder_id=account.id,
            )
            db.commit()
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    return {"status": "ok"}
