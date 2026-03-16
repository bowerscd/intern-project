"""Admin endpoints — claim review, account approval, and account management.

Only accounts with the ``ADMIN`` claim can access these endpoints.
"""

import logging
from datetime import datetime, UTC
from typing import Annotated, Any, Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from csrf import validate_csrf_token
from models import (
    AccountClaims,
    AccountClaimStatus,
    AccountStatus,
    DBAccount as Account,
    DBAccountClaimRequest as AccountClaimRequest,
    ExternalAuthProvider,
)
from routes.shared import Database, RequireLogin
from schemas.account import ClaimRequestResponse, ClaimReviewRequest

from .router import Accounts

logger = logging.getLogger(__name__)


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
            logger.warning(
                "Admin claim review: claim #%d not found (admin #%d)",
                claim_id,
                account.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Claim request not found.",
            )

        current_status = _status_str(claim.status)
        if current_status != AccountClaimStatus.PENDING.value:
            logger.warning(
                "Admin claim review: claim #%d already %s (admin #%d)",
                claim_id,
                current_status,
                account.id,
            )
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
                logger.warning(
                    "Admin claim approve: target account #%d deleted (claim #%d, admin #%d)",
                    claim.target_account_id,
                    claim_id,
                    account.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target account no longer exists.",
                )

            # Safety guard: only allow approving claims against legacy accounts.
            # This is defence-in-depth — the claim endpoint already enforces
            # this, but a direct DB manipulation or future code path could
            # bypass it.
            if not target.external_unique_id.startswith("legacy-"):
                logger.warning(
                    "Admin claim approve: target account #%d already OIDC-linked "
                    "(claim #%d, admin #%d)",
                    claim.target_account_id,
                    claim_id,
                    account.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot approve: target account is already linked "
                    "to an OIDC identity.",
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
        target_username = target_act.username if target_act else "<deleted>"

        logger.info(
            "Admin %s (#%d) %s claim #%d (requester=%s, target=%s #%d)",
            account.username,
            account.id,
            decision,
            claim.id,
            claim.requester_name,
            target_username,
            claim.target_account_id,
            extra={
                "action": "claim_review",
                "admin_id": account.id,
                "admin_username": account.username,
                "claim_id": claim.id,
                "decision": decision,
                "requester_name": claim.requester_name,
                "target_account_id": claim.target_account_id,
                "target_username": target_username,
            },
        )

        return _claim_response(claim, target_username)


# ── Schemas for admin account management ──────────────────────────────


class AdminAccountResponse(BaseModel):
    """Response schema for an account in the admin view.

    :cvar id: Account primary key.
    :cvar username: Unique username.
    :cvar email: Email address, or ``None``.
    :cvar status: Current account status string.
    :cvar claims: Bitmask of account claims.
    :cvar provider: External auth provider name.
    """

    id: int
    username: str
    email: Optional[str]
    status: str
    claims: int
    provider: str


class AdminStatusUpdateRequest(BaseModel):
    """Request schema for updating an account's status.

    :cvar status: Target status value.
    """

    status: str = Field(
        ...,
        description="Target status: 'active', 'banned', or 'defunct'",
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Ensure status is one of the allowed transition values.

        :param v: Candidate status.
        :returns: The validated status.
        :raises ValueError: If the status is not allowed.
        """
        allowed = {"active", "banned", "defunct"}
        if v.lower() not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(sorted(allowed))}")
        return v.lower()


class AdminRoleUpdateRequest(BaseModel):
    """Request schema for updating an account's admin role.

    :cvar grant_admin: Whether to grant or revoke the ADMIN claim.
    """

    grant_admin: bool = Field(
        ...,
        description="True to grant ADMIN, False to revoke it",
    )


def _account_response(act: Account) -> AdminAccountResponse:
    """Build an :class:`AdminAccountResponse` from an Account ORM object."""
    return AdminAccountResponse(
        id=act.id,
        username=act.username,
        email=act.email,
        status=_status_str(act.status),
        claims=int(act.claims) if hasattr(act.claims, "__int__") else act.claims,
        provider=_provider_str(act.account_provider),
    )


# ── Admin account list & management endpoints ─────────────────────────


@Accounts.get(
    "/admin/accounts",
    summary="List all accounts",
    description="Return all accounts with optional status filter. Requires ADMIN claim.",
    response_model=list[AdminAccountResponse],
)
async def list_accounts(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.ADMIN))],
    db: Database,
    status_filter: Optional[str] = None,
) -> list[AdminAccountResponse]:
    """Return all accounts, optionally filtered by status.

    :param account: The authenticated admin account.
    :param db: Active database session.
    :param status_filter: Optional status string to filter by.
    :returns: A list of :class:`AdminAccountResponse`.
    :rtype: list[AdminAccountResponse]
    """
    with db:
        query = select(Account)
        if status_filter:
            try:
                target_status = AccountStatus(status_filter.lower())
            except ValueError:
                logger.warning(
                    "Admin accounts: invalid status_filter=%r from admin #%d",
                    status_filter,
                    account.id,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status filter: {status_filter}",
                )
            query = query.where(Account.status == target_status)
            # Exclude legacy (unclaimed) accounts from pending lists — they
            # should only appear once someone submits a claim for them.
            if target_status == AccountStatus.PENDING_APPROVAL:
                query = query.where(~Account.external_unique_id.like("legacy-%"))
        query = query.order_by(Account.id)
        accounts = list(db.scalars(query).all())
        return [_account_response(a) for a in accounts]


@Accounts.post(
    "/admin/accounts/{account_id}/status",
    summary="Update account status",
    dependencies=[Depends(validate_csrf_token)],
    description="Change an account's status (approve, ban, or defunct). Requires ADMIN claim.",
    response_model=AdminAccountResponse,
)
async def update_account_status(
    account_id: int,
    body: AdminStatusUpdateRequest,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.ADMIN))],
    db: Database,
) -> AdminAccountResponse:
    """Update the status of an account.

    :param account_id: Primary key of the target account.
    :param body: The status update request.
    :param account: The authenticated admin account.
    :param db: Active database session.
    :returns: The updated :class:`AdminAccountResponse`.
    :rtype: AdminAccountResponse
    :raises HTTPException: 404 if account not found, 400 on invalid transition.
    """
    with db:
        target = db.scalars(select(Account).where(Account.id == account_id)).first()

        if target is None:
            logger.warning(
                "Admin status update: account #%d not found (admin #%d)",
                account_id,
                account.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found.",
            )

        try:
            new_status = AccountStatus(body.status)
        except ValueError:
            logger.warning(
                "Admin status update: invalid status=%r for account #%d (admin #%d)",
                body.status,
                account_id,
                account.id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {body.status}",
            )

        old_status = _status_str(target.status)
        target.status = new_status  # type: ignore[assignment]
        db.commit()
        db.refresh(target)
        logger.info(
            "Admin %s (#%d) changed account #%d (%s) status: %s → %s",
            account.username,
            account.id,
            target.id,
            target.username,
            old_status,
            body.status,
            extra={
                "action": "admin_status_change",
                "admin_id": account.id,
                "admin_username": account.username,
                "target_id": target.id,
                "target_username": target.username,
                "old_status": old_status,
                "new_status": body.status,
            },
        )
        return _account_response(target)


@Accounts.post(
    "/admin/accounts/{account_id}/role",
    summary="Update account admin role",
    dependencies=[Depends(validate_csrf_token)],
    description="Grant or revoke the ADMIN claim on an account. Requires ADMIN claim.",
    response_model=AdminAccountResponse,
)
async def update_account_role(
    account_id: int,
    body: AdminRoleUpdateRequest,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.ADMIN))],
    db: Database,
) -> AdminAccountResponse:
    """Grant or revoke the ADMIN claim on an account.

    :param account_id: Primary key of the target account.
    :param body: The role update request.
    :param account: The authenticated admin account.
    :param db: Active database session.
    :returns: The updated :class:`AdminAccountResponse`.
    :rtype: AdminAccountResponse
    :raises HTTPException: 404 if account not found.
    """
    with db:
        target = db.scalars(select(Account).where(Account.id == account_id)).first()

        if target is None:
            logger.warning(
                "Admin role update: account #%d not found (admin #%d)",
                account_id,
                account.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found.",
            )

        old_claims = (
            int(target.claims) if hasattr(target.claims, "__int__") else target.claims
        )
        if body.grant_admin:
            target.claims = target.claims | AccountClaims.ADMIN  # type: ignore[assignment]
        else:
            target.claims = target.claims & ~AccountClaims.ADMIN  # type: ignore[assignment]

        db.commit()
        db.refresh(target)
        new_claims = (
            int(target.claims) if hasattr(target.claims, "__int__") else target.claims
        )
        logger.info(
            "Admin %s (#%d) %s ADMIN role on account #%d (%s): claims %d → %d",
            account.username,
            account.id,
            "granted" if body.grant_admin else "revoked",
            target.id,
            target.username,
            old_claims,
            new_claims,
            extra={
                "action": "admin_role_change",
                "admin_id": account.id,
                "admin_username": account.username,
                "target_id": target.id,
                "target_username": target.username,
                "grant_admin": body.grant_admin,
                "old_claims": old_claims,
                "new_claims": new_claims,
            },
        )
        return _account_response(target)
