"""
Self-service claims management endpoint — authenticated.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from sqlalchemy import select

from routes.shared import Database, RequireLogin
from models import AccountClaims, DBAccount as Account
from csrf import validate_csrf_token

from schemas.account import ClaimsUpdate, ProfileResponse

from .router import Accounts

# Claims that cannot be self-assigned or self-removed
BLOCKED_CLAIMS = frozenset({"ADMIN", "BASIC"})


@Accounts.patch(
    "/claims",
    summary="Update own claims",
    dependencies=[Depends(validate_csrf_token)],
    description="Add or remove permission claims on the authenticated user's account. "
    "The ADMIN claim cannot be modified through this endpoint.",
    response_model=ProfileResponse,
)
async def update_claims(
    body: ClaimsUpdate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.BASIC))],
    db: Database,
) -> ProfileResponse:
    """Add or remove permission claims on the authenticated user's account.

    The ``ADMIN`` claim cannot be modified through this endpoint.

    :param body: The claims update payload listing claims to add/remove.
    :param account: The authenticated account.
    :param db: Active database session.
    :returns: The updated :class:`ProfileResponse`.
    :rtype: ProfileResponse
    :raises HTTPException: If blocked or invalid claim names are
        requested, or the account is not found.
    """
    # Validate that no blocked claims are requested
    all_requested = set(body.add) | set(body.remove)
    blocked = all_requested & BLOCKED_CLAIMS
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot modify admin-level claims: {', '.join(sorted(blocked))}",
        )

    # Validate all claim names
    valid_names = {c.name for c in AccountClaims if c.name != "ANY"}
    invalid = all_requested - valid_names
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid claim names: {', '.join(sorted(invalid))}",
        )

    with db:
        act = db.scalars(select(Account).where(Account.id == account.id)).first()
        if act is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        current_claims = act.claims

        # Apply additions
        for name in body.add:
            current_claims |= AccountClaims[name]

        # Apply removals
        for name in body.remove:
            current_claims &= ~AccountClaims[name]

        # Enforce: HAPPY_HOUR_TYRANT always implies HAPPY_HOUR
        if current_claims & AccountClaims.HAPPY_HOUR_TYRANT:
            current_claims |= AccountClaims.HAPPY_HOUR

        act.claims = current_claims
        db.commit()
        db.refresh(act)

        return ProfileResponse.from_account(act)
