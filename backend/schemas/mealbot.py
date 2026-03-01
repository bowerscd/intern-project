"""
Pydantic schemas for Mealbot API request/response models.
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


# --- v1 schemas (backwards-compatible) ---

class AccountModificationRequest(BaseModel):
    """Request schema for creating a v1 user account."""

    user: str = Field(..., pattern=r"^[a-z]{3}[a-z]+$", description="Username (lowercase, minimum 4 chars)")
    operation: Literal["CREATE"] = Field(..., description="Operation to perform")


class CreateRecordRequest(BaseModel):
    """Request schema for creating a meal credit record."""

    payer: str = Field(..., description="Username of the payer")
    recipient: str = Field(..., description="Username of the recipient")
    credits: int = Field(..., gt=0, le=1000, description="Number of credits (positive integer, max 1000)")


class RecordResponse(BaseModel):
    """Response schema representing a single meal credit record."""

    model_config = ConfigDict(populate_by_name=True)

    payer: str = Field(..., description="Username of the payer")
    recipient: str = Field(..., description="Username of the recipient")
    credits: int = Field(..., description="Number of credits")
    date: datetime = Field(..., description="When the record was created")

    @staticmethod
    def from_receipt(r: Any) -> 'RecordResponse':
        """Build a :class:`RecordResponse` from a database receipt entity.

        :param r: A :class:`Receipt` ORM instance.
        :returns: A populated response model.
        :rtype: RecordResponse
        """
        return RecordResponse(
            payer=r.Payer.username,
            recipient=r.Recipient.username,
            credits=r.Credits,
            date=r.Time,
        )


class PaginatedRecordResponse(BaseModel):
    """Paginated wrapper for record responses."""

    items: list[RecordResponse] = Field(..., description="Page of record items")
    total: int = Field(..., description="Total number of items across all pages")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Maximum items per page")
