"""Tyrant rotation assignment ORM model."""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Model
from models.internal import SqlValueEnum
from models.account import Account
from models.enums import TyrantAssignmentStatus


class TyrantRotation(Model):
    """Tyrant rotation assignment persisted in the ``HappyHourTyrantRotation`` table.

    Tracks which user is assigned to choose the happy hour venue for a
    given rotation cycle, along with deadlines, position in the
    rotation order, and completion status.
    """

    __tablename__ = "HappyHourTyrantRotation"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    Account: Mapped[Account] = relationship("Account")
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    assigned_at: Mapped[datetime] = mapped_column(insert_default=lambda: datetime.now(UTC))
    deadline_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, default=None)
    status: Mapped[TyrantAssignmentStatus] = mapped_column(
        SqlValueEnum(TyrantAssignmentStatus),
        default=TyrantAssignmentStatus.SCHEDULED,
    )

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the rotation.

        :returns: A string showing id, account_id, cycle, position, and status.
        :rtype: str
        """
        return (
            f"<TyrantRotation id={self.id} account_id={self.account_id} "
            f"cycle={self.cycle} position={self.position} status={self.status}>"
        )
