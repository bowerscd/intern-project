"""Meal credit receipt ORM model."""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Model
from models.account import Account


class Receipt(Model):
    """Meal credit receipt persisted in the ``receipts`` table.

    Records a transfer of meal credits from a payer to a recipient,
    optionally noting who recorded the transaction.
    """

    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(
            '"PayerId" != "RecipientId"', name="ck_receipts_no_self_payment"
        ),
        CheckConstraint('"Credits" > 0', name="ck_receipts_positive_credits"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    Credits: Mapped[int]
    Time: Mapped[datetime] = mapped_column(
        insert_default=lambda: datetime.now(UTC), index=True
    )

    RecorderId: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"))
    Recorder: Mapped[Optional[Account]] = relationship(
        "Account", foreign_keys=[RecorderId]
    )

    PayerId: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    Payer: Mapped[Account] = relationship("Account", foreign_keys=[PayerId])

    RecipientId: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    Recipient: Mapped[Account] = relationship("Account", foreign_keys=[RecipientId])

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the receipt.

        :returns: A string showing the payer, recipient and credit amount.
        :rtype: str
        """
        return f"<Receipt id={self.id!r} (payer) {self.Payer!r} --{self.Credits!r}--> {self.Recipient!r}>"
