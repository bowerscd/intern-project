"""Account claim request ORM model."""

from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Model
from models.enums import ExternalAuthProvider, AccountClaimStatus
from models.internal import SqlValueEnum


class AccountClaimRequest(Model):
    """Tracks a request by a new OIDC user to claim ownership of a legacy account.

    An admin must approve the claim before the legacy account's
    ``account_provider`` and ``external_unique_id`` are updated to
    match the claimant's OIDC identity.
    """

    __tablename__ = "account_claim_requests"

    id: Mapped[int] = mapped_column(primary_key=True)

    requester_provider: Mapped[ExternalAuthProvider] = mapped_column(
        SqlValueEnum(ExternalAuthProvider),
        comment="OIDC provider of the user making the claim",
    )
    requester_external_id: Mapped[str] = mapped_column(
        String(),
        comment="OIDC 'sub' of the user making the claim",
    )
    requester_name: Mapped[str] = mapped_column(
        String(),
        comment="Display name from the OIDC identity (for admin review)",
    )
    requester_email: Mapped[Optional[str]] = mapped_column(
        String(),
        nullable=True,
        comment="Email from the OIDC identity (for admin review)",
    )

    target_account_id: Mapped[int] = mapped_column(
        Integer(),
        ForeignKey("accounts.id"),
        comment="The legacy account being claimed",
    )

    status: Mapped[str] = mapped_column(
        SqlValueEnum(AccountClaimStatus),
        default=AccountClaimStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
