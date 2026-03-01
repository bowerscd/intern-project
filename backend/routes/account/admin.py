"""Admin endpoints — claim review and approval.

Only accounts with the ``ADMIN`` claim can access these endpoints.
"""

from datetime import datetime, UTC
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from csrf import validate_csrf_token
from models import (
    AccountClaims,
    AccountClaimStatus,
    DBAccount as Account,
    DBAccountClaimRequest as AccountClaimRequest,
    ExternalAuthProvider,
)
from routes.shared import Database, RequireLogin
from schemas.account import ClaimRequestResponse, ClaimReviewRequest

from .router import Accounts


def _status_str(raw: Any) -> str:
    """Extract the string value from a status field (enum or plain str)."""
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw)


def _provider_str(raw: Any) -> str:
    """Extract the string name from an ExternalAuthProvider (or plain str)."""
    if hasattr(raw, "name"):
        return str(raw.name)
    return str(raw)


def _claim_response(
    claim: AccountClaimRequest, target_username: str
) -> ClaimRequestResponse:
    """Build a :class:`ClaimRequestResponse` from a claim ORM object."""
    resolved = None
    if claim.resolved_at is not None:
        resolved = (
            claim.resolved_at.isoformat()
            if hasattr(claim.resolved_at, "isoformat")
            else str(claim.resolved_at)
        )
    created = (
        claim.created_at.isoformat()
        if hasattr(claim.created_at, "isoformat")
        else str(claim.created_at)
    )

    return ClaimRequestResponse(
        id=claim.id,
        requester_provider=_provider_str(claim.requester_provider),
        requester_external_id=claim.requester_external_id,
        requester_name=claim.requester_name,
        requester_email=claim.requester_email,
        target_account_id=claim.target_account_id,
        target_username=target_username,
        status=_status_str(claim.status),
        created_at=created,
        resolved_at=resolved,
    )


@Accounts.get(
    "/admin/claims",
    summary="List account claim requests",
    description="Return all pending account claim requests. Requires ADMIN claim.",
    response_model=list[ClaimRequestResponse],
)
async def list_claim_requests(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.ADMIN))],
    db: Database,
    include_resolved: bool = False,
) -> list[ClaimRequestResponse]:
    """Return pending (or all) account claim requests for admin review.

    :param account: The authenticated admin account.
    :param db: Active database session.
    :param include_resolved: If ``True``, include approved/denied claims.
    :returns: A list of :class:`ClaimRequestResponse`.
    :rtype: list[ClaimRequestResponse]
    """
    with db:
        query = select(AccountClaimRequest)
        if not include_resolved:
            query = query.where(
                AccountClaimRequest.status == AccountClaimStatus.PENDING
            )
        query = query.order_by(AccountClaimRequest.created_at.desc())
        claims = list(db.scalars(query).all())

        results: list[ClaimRequestResponse] = []
        for c in claims:
            target = db.scalars(
                select(Account).where(Account.id == c.target_account_id)
            ).first()
            results.append(
                _claim_response(c, target.username if target else "<deleted>")
            )
        return results


@Accounts.post(
    "/admin/claims/{claim_id}/review",
    summary="Approve or deny an account claim",
    dependencies=[Depends(validate_csrf_token)],
    description="Approve or deny a pending account claim request. On approval, "
    "the target account's external identity is updated to match the "
    "claimant. Requires ADMIN claim.",
    response_model=ClaimRequestResponse,
)
async def review_claim_request(
    claim_id: int,
    body: ClaimReviewRequest,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.ADMIN))],
    db: Database,
) -> ClaimRequestResponse:
    """Approve or deny a pending account claim request.

    On approval the target legacy account's ``account_provider`` and
    ``external_unique_id`` are updated to match the claimant's OIDC
    identity, enabling them to log in as that account.

    :param claim_id: Primary key of the claim request.
    :param body: The review decision (approve or deny).
    :param account: The authenticated admin account.
    :param db: Active database session.
    :returns: The updated :class:`ClaimRequestResponse`.
    :rtype: ClaimRequestResponse
    :raises HTTPException: 404 if the claim is not found, 409 if it is
        already resolved, 400 if the decision is invalid.
    """
    decision = body.decision.lower()
    if decision not in ("approve", "deny"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decision must be 'approve' or 'deny'.",
        )

    with db:
        claim = db.scalars(
            select(AccountClaimRequest).where(AccountClaimRequest.id == claim_id)
        ).first()

        if claim is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Claim request not found.",
            )

        current_status = _status_str(claim.status)
        if current_status != AccountClaimStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Claim is already {current_status}.",
            )

        now = datetime.now(UTC)

        if decision == "approve":
            # Update the target account's external identity
            target = db.scalars(
                select(Account).where(Account.id == claim.target_account_id)
            ).first()
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target account no longer exists.",
                )

            target.account_provider = ExternalAuthProvider[
                claim.requester_provider.name
            ]  # type: ignore[union-attr]
            target.external_unique_id = claim.requester_external_id

            # Grant BASIC claim if the account doesn't have it
            if not (target.claims & AccountClaims.BASIC):
                target.claims = target.claims | AccountClaims.BASIC

            claim.status = AccountClaimStatus.APPROVED  # type: ignore[assignment]
            claim.resolved_at = now  # type: ignore[assignment]
        else:
            claim.status = AccountClaimStatus.DENIED  # type: ignore[assignment]
            claim.resolved_at = now  # type: ignore[assignment]

        db.commit()
        db.refresh(claim)

        target_act = db.scalars(
            select(Account).where(Account.id == claim.target_account_id)
        ).first()

        return _claim_response(
            claim, target_act.username if target_act else "<deleted>"
        )
