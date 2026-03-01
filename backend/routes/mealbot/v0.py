"""
Legacy v0 API endpoints — backwards compatible with special-tribble.

.. deprecated::
    These endpoints are **permanently disabled** and always return
    ``410 Gone``.  The code is retained for historical reference only.
    Use the v2 API instead.
"""

from typing import Any

from fastapi import APIRouter, Request, Response, HTTPException, status
from routes.tags import ApiTags
from routes.shared import (
    Database,
    reject_if_legacy_disabled,
    mark_legacy_routes_deprecated,
)


MealbotV0 = APIRouter(
    tags=[ApiTags.Legacy],
)


@MealbotV0.post(
    "/echo",
    summary="Echo request body",
    description="Returns the request body as plain text. Legacy endpoint.",
)
@reject_if_legacy_disabled
async def echo(request: Request) -> Response:
    """Echo the request body as plain text.

    :param request: The incoming :class:`Request`.
    :returns: A plain-text :class:`Response` containing the body.
    :rtype: Response
    """
    body = await request.body()
    return Response(content=body, media_type="text/plain")


@MealbotV0.get(
    "/get-data",
    summary="Get legacy database dump",
    description="Returns all users and receipts in the legacy format.",
)
@reject_if_legacy_disabled
async def get_data(db: Database) -> dict[str, Any]:
    """Return all users and receipts in the legacy database format.

    :param db: Active database session.
    :returns: A dict with ``Users`` and ``Reciepts`` keys.
    :rtype: dict[str, Any]
    """
    from sqlalchemy import select
    from models import DBAccount as Account, DBReceipt as Receipt

    with db:
        accounts = db.scalars(select(Account)).all()
        receipts = db.scalars(select(Receipt).order_by(Receipt.Time.asc())).all()

    users = [{"ID": a.id, "UPN": a.username} for a in accounts]

    reciepts = []
    for r in receipts:
        reciepts.append(
            {
                "Payer": r.PayerId,
                "Payee": r.RecipientId,
                "NumMeals": r.Credits,
                "DateTime": r.Time.isoformat() if r.Time else "",
            }
        )

    return {"Users": users, "Reciepts": reciepts}


@MealbotV0.post(
    "/edit_meal/{Payer}/{Recipient}/{Payment}",
    summary="Edit a meal record (legacy)",
    description="Create a meal record. Negative payment flips payer/recipient. Legacy endpoint.",
)
@reject_if_legacy_disabled
async def edit_meal(Payer: str, Recipient: str, Payment: int, db: Database) -> Response:
    """Create a meal record via the legacy URL-parameter interface.

    A negative *Payment* flips the payer and recipient.

    :param Payer: Username of the payer.
    :param Recipient: Username of the recipient.
    :param Payment: Credit amount (negative flips direction).
    :param db: Active database session.
    :returns: A ``200 OK`` response on success.
    :rtype: Response
    :raises HTTPException: If the payer/recipient are the same or do not
        exist.
    """
    from db.functions import create_receipt

    with db:
        if Payment >= 0:
            actual_payer = Payer
            actual_recipient = Recipient
            actual_credits = Payment
        else:
            actual_payer = Recipient
            actual_recipient = Payer
            actual_credits = abs(Payment)

        if actual_payer == actual_recipient:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payer and recipient cannot be the same person",
            )

        try:
            create_receipt(db, actual_payer, actual_recipient, actual_credits)
            db.commit()
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return Response(status_code=status.HTTP_200_OK)


@MealbotV0.get(
    "/whoami/{UserID}",
    summary="Get username by ID (legacy)",
    description="Returns the username for a given user ID as plain text. Legacy endpoint.",
)
@reject_if_legacy_disabled
async def whoami(UserID: int, db: Database) -> Response:
    """Return the username for a given account ID.

    :param UserID: The account's integer ID.
    :param db: Active database session.
    :returns: A plain-text response containing the username.
    :rtype: Response
    :raises HTTPException: If the account is not found.
    """
    from db.functions import get_account_by_id

    with db:
        account = get_account_by_id(db, UserID)

        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        return Response(content=account.username, media_type="text/plain")


mark_legacy_routes_deprecated(MealbotV0)
