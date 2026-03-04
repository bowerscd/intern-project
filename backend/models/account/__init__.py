"""Account ORM model."""

from typing import Optional

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Model
from models.enums import (
    PhoneProvider,
    ExternalAuthProvider,
    AccountClaims,
    AccountStatus,
)
from models.internal import SqlValueEnum


class Account(Model):
    """User account entity persisted in the ``accounts`` table.

    Stores authentication credentials, contact information, and
    permission claims for each registered user.
    """

    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)

    username: Mapped[str] = mapped_column(String(), unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(), unique=True)

    phone: Mapped[Optional[str]] = mapped_column(String(), unique=True)
    phone_provider: Mapped[int] = mapped_column(
        SqlValueEnum(PhoneProvider), default=PhoneProvider.NONE
    )

    account_provider: Mapped[ExternalAuthProvider] = mapped_column(
        SqlValueEnum(ExternalAuthProvider)
    )
    external_unique_id: Mapped[str] = mapped_column(String())

    claims: Mapped[int] = mapped_column(
        SqlValueEnum(AccountClaims), default=AccountClaims.NONE
    )

    status: Mapped[AccountStatus] = mapped_column(
        SqlValueEnum(AccountStatus),
        default=AccountStatus.PENDING_APPROVAL,
        server_default=AccountStatus.PENDING_APPROVAL.value,
    )

    __table_args__ = (UniqueConstraint("account_provider", "external_unique_id"),)

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the account.

        :returns: A string showing the account's id, username and claims.
        :rtype: str
        """
        return (
            f"<User id={self.id!r} username={self.username!r} claims={self.claims!r}>"
        )
