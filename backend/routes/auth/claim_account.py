"""POST /claim-account — request ownership of an existing legacy account."""

from fastapi import Depends, HTTPException, Request, status

from csrf import validate_csrf_token
from db.functions import get_account_by_username
from models import (
    ExternalAuthProvider,
    DBAccount as Account,
    DBAccountClaimRequest as AccountClaimRequest,
    AccountClaimStatus,
)
from routes.shared import Database
from schemas.account import ClaimAccountRequest
from ratelimit import limiter
from sqlalchemy import select, and_

from .authenticate import PENDING_REGISTRATION_KEY
from .router import Authentication

LEGACY_PLACEHOLDER_SUB = "legacy-placeholder"


@Authentication.get(
    "/claimable-accounts",
    summary="List claimable accounts",
    description="Returns usernames of legacy accounts not yet linked to an OIDC identity.",
    response_model=list[str],
)
async def list_claimable_accounts(db: Database) -> list[str]:
    """Return usernames of unlinked legacy accounts available to claim.

    An account is claimable if its ``external_unique_id`` is still the
    legacy placeholder, meaning it has not yet been linked to any OIDC
    identity.

    :param db: Active database session.
    :returns: Sorted list of claimable usernames.
    :rtype: list[str]
    """
    with db:
        rows = db.scalars(
            select(Account.username).where(
                Account.external_unique_id == LEGACY_PLACEHOLDER_SUB
            )
        ).all()
    return sorted(rows)


@Authentication.post(
    "/claim-account",
    summary="Claim legacy account",
    dependencies=[Depends(validate_csrf_token)],
    description="After OIDC authentication in register mode, the user can "
    "claim ownership of an existing (imported/legacy) account. "
    "An admin must approve the claim before login is possible.",
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("5/minute")
async def claim_account(
    request: Request,
    body: ClaimAccountRequest,
    db: Database,
) -> dict:
    """Submit a request to claim ownership of an existing account.

    Reads ``pending_registration`` from the session, looks up the
    target account by username, and creates a pending
    :class:`AccountClaimRequest`.  The claim must be approved by an
    admin before the account's external identity is updated.

    :param request: The incoming :class:`Request`.
    :param body: Payload with the username of the account to claim.
    :param db: Active database session.
    :returns: Confirmation dict with the claim request id and status.
    :raises HTTPException: 401 if no pending registration, 404 if the
        target username doesn't exist, 409 if there is already a
        pending claim for this target by the same requester.
    """
    pending = request.session.get(PENDING_REGISTRATION_KEY)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No pending registration. Please start the registration flow.",
        )

    provider = ExternalAuthProvider[pending["provider"]]
    sub = pending["sub"]

    with db:
        target = get_account_by_username(db, body.username)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Claim request could not be processed.",
            )

        # Check for an existing pending claim by the same requester
        existing = db.scalars(
            select(AccountClaimRequest).where(
                and_(
                    AccountClaimRequest.requester_provider == provider,
                    AccountClaimRequest.requester_external_id == sub,
                    AccountClaimRequest.target_account_id == target.id,
                    AccountClaimRequest.status == AccountClaimStatus.PENDING,
                )
            )
        ).first()

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have a pending claim for this account.",
            )

        claim = AccountClaimRequest(
            requester_provider=provider,
            requester_external_id=sub,
            requester_name=pending.get("name", ""),
            requester_email=pending.get("email"),
            target_account_id=target.id,
            status=AccountClaimStatus.PENDING,
        )
        db.add(claim)
        db.commit()

        claim_id = claim.id

    return {
        "claim_id": claim_id,
        "status": "pending",
        "message": "Your claim has been submitted. An admin will review it.",
    }
