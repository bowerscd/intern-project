"""POST /claim-account — request ownership of an existing legacy account."""

import logging

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

logger = logging.getLogger(__name__)

LEGACY_PREFIX = "legacy-"


@Authentication.get(
    "/claimable-accounts",
    summary="List claimable accounts",
    description="Returns usernames of legacy accounts not yet linked to an OIDC identity.",
    response_model=list[str],
)
@limiter.limit("10/minute")
async def list_claimable_accounts(request: Request, db: Database) -> list[str]:
    """Return usernames of unlinked legacy accounts available to claim.

    An account is claimable if its ``external_unique_id`` starts with
    the legacy prefix, meaning it has not yet been linked to any OIDC
    identity.

    :param db: Active database session.
    :returns: Sorted list of claimable usernames.
    :rtype: list[str]
    """
    with db:
        rows = db.scalars(
            select(Account.username).where(
                Account.external_unique_id.like(f"{LEGACY_PREFIX}%")
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
        logger.warning("Claim attempt with no pending registration in session")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No pending registration. Please start the registration flow.",
        )

    provider = ExternalAuthProvider[pending["provider"]]
    sub = pending["sub"]

    with db:
        target = get_account_by_username(db, body.username)
        if target is None:
            logger.warning(
                "Claim attempt for non-existent username=%r by sub=%s",
                body.username,
                sub,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Claim request could not be processed.",
            )

        # Only legacy (unlinked) accounts may be claimed — reject attempts
        # to claim active OIDC-linked accounts to prevent account takeover.
        if not target.external_unique_id.startswith(LEGACY_PREFIX):
            logger.warning(
                "Claim attempt on non-legacy account=%r (ext_id=%s) by sub=%s",
                body.username,
                target.external_unique_id[:8] + "...",
                sub,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account cannot be claimed.",
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
            logger.info(
                "Duplicate claim attempt: sub=%s already has pending claim for account=%r",
                sub,
                body.username,
            )
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
