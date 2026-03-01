"""
Account profile endpoints — authenticated.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from routes.shared import Database, RequireLogin
from models import AccountClaims
from csrf import validate_csrf_token
from models.enums import PhoneProvider

from schemas.account import ProfileResponse, ProfileUpdate

from .router import Accounts


@Accounts.get(
    "/profile",
    summary="Get user profile",
    description="Get the authenticated user's profile information. Requires BASIC claim.",
    response_model=ProfileResponse,
)
async def get_profile(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.BASIC))],
) -> ProfileResponse:
    """Return the authenticated user's profile.

    :param account: The authenticated account (injected by
        :class:`RequireLogin`).
    :returns: A :class:`ProfileResponse` for the current user.
    :rtype: ProfileResponse
    """
    return ProfileResponse.from_account(account)


@Accounts.patch(
    "/profile",
    summary="Update user profile",
    dependencies=[Depends(validate_csrf_token)],
    description="Update the authenticated user's phone number and carrier for SMS notifications. "
    "Requires BASIC claim.",
    response_model=ProfileResponse,
)
async def update_profile(
    body: ProfileUpdate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.BASIC))],
    db: Database,
) -> ProfileResponse:
    """Update the authenticated user's phone and carrier settings.

    :param body: The profile update payload.
    :param account: The authenticated account.
    :param db: Active database session.
    :returns: The updated :class:`ProfileResponse`.
    :rtype: ProfileResponse
    :raises HTTPException: If the account is not found or the phone
        provider is invalid.
    """
    with db:
        from sqlalchemy import select
        from models import DBAccount as Account

        act = db.scalars(select(Account).where(Account.id == account.id)).first()
        if act is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        if body.phone is not None:
            act.phone = body.phone

        if body.phone_provider is not None:
            try:
                provider = PhoneProvider[body.phone_provider]
                act.phone_provider = provider
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid phone provider: {body.phone_provider}",
                )

        db.commit()
        db.refresh(act)

        return ProfileResponse.from_account(act)
