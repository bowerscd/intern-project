"""
v2 Mealbot API endpoints — authenticated.
Requires MEALBOT claim for most operations.
"""

import logging
from typing import Annotated, Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query

from routes.tags import ApiTags
from routes.shared import Database, RequireLogin, require_write_access
from csrf import validate_csrf_token

from models import AccountClaims
from schemas.mealbot import (
    RecordResponse,
    PaginatedRecordResponse,
    CreateRecordRequest,
)

logger = logging.getLogger(__name__)

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
        receipts = get_records_for_user_paginated(
            db, account.username, offset, page_size
        )

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

    require_write_access(account)

    # Capture values before the session closes (lesson #034)
    recorder_id = account.id
    recorder_username = account.username

    if body.payer == body.recipient:
        logger.warning(
            "Mealbot record: payer==recipient=%r by account #%d",
            body.payer,
            recorder_id,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payer and recipient cannot be the same person",
        )

    if account.username not in (body.payer, body.recipient):
        logger.warning(
            "Mealbot record: account #%d (%s) not involved in payer=%r recipient=%r",
            recorder_id,
            recorder_username,
            body.payer,
            body.recipient,
        )
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
                recorder_id=recorder_id,
            )
            db.commit()
        except ValueError as e:
            logger.warning(
                "Mealbot record: validation error=%s (payer=%r recipient=%r recorder=#%d)",
                e,
                body.payer,
                body.recipient,
                recorder_id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    logger.info(
        "Mealbot record: %s paid for %s (%d credits), recorded by %s (#%d)",
        body.payer,
        body.recipient,
        body.credits,
        recorder_username,
        recorder_id,
        extra={
            "action": "mealbot_record",
            "payer": body.payer,
            "recipient": body.recipient,
            "credits": body.credits,
            "recorder_id": recorder_id,
            "recorder_username": recorder_username,
        },
    )
    return {"status": "ok"}


@MealbotV2.delete(
    "/record/{record_id}",
    summary="Void a meal record",
    dependencies=[Depends(validate_csrf_token)],
    description="Delete (void) a mistaken meal credit record. The payer, "
    "recipient, original recorder, or any ADMIN can void a record. Requires MEALBOT claim.",
    status_code=status.HTTP_200_OK,
)
async def void_record(
    record_id: int,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.MEALBOT))],
    db: Database,
) -> dict[str, Any]:
    """Void (delete) a meal credit record.

    The payer, recipient, or original recorder of the record may void
    it.  Users with the ``ADMIN`` claim may void any record.  This is
    a disaster recovery mechanism for correcting mistakes — duplicate
    entries, wrong person, wrong amount, etc.

    :param record_id: The record's integer ID.
    :param account: The authenticated account with ``MEALBOT`` claim.
    :param db: Active database session.
    :returns: A status dict.
    :raises HTTPException: If the record is not found or the caller is
        not authorized to void it.
    """
    from db.functions import get_receipt_by_id, delete_receipt

    require_write_access(account)

    # Capture values before the session closes (lesson #034)
    account_id = account.id
    account_username = account.username
    is_admin = (account.claims & AccountClaims.ADMIN) == AccountClaims.ADMIN

    with db:
        receipt = get_receipt_by_id(db, record_id)
        if receipt is None:
            logger.warning(
                "Mealbot void: record #%d not found (account #%d)",
                record_id,
                account_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Record not found",
            )

        # ADMIN can void any record; others must be payer, recipient, or recorder
        if not is_admin:
            allowed_ids = {receipt.PayerId, receipt.RecipientId}
            if receipt.RecorderId is not None:
                allowed_ids.add(receipt.RecorderId)

            if account_id not in allowed_ids:
                logger.warning(
                    "Mealbot void: account #%d not authorized to void record #%d",
                    account_id,
                    record_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only void records you are involved in",
                )

        # Capture info for logging before deletion (lesson #034)
        payer_name = receipt.Payer.username
        recipient_name = receipt.Recipient.username
        credits = receipt.Credits

        delete_receipt(db, record_id)
        db.commit()

    logger.info(
        "Mealbot void: record #%d (%s -> %s, %d credits) voided by %s (#%d)",
        record_id,
        payer_name,
        recipient_name,
        credits,
        account_username,
        account_id,
        extra={
            "action": "mealbot_void",
            "record_id": record_id,
            "payer": payer_name,
            "recipient": recipient_name,
            "credits": credits,
            "voided_by_id": account_id,
            "voided_by_username": account_username,
        },
    )
    return {"status": "voided", "record_id": record_id}
