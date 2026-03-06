"""
Pydantic schemas for Happy Hour API request/response models.
"""

from datetime import datetime, UTC
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class LocationCreate(BaseModel):
    """Request schema for creating a new happy hour location.

    All address and coordinate fields are required.
    """

    name: str = Field(..., description="Name of the venue", max_length=200)
    url: Optional[str] = Field(
        None, description="Website URL", pattern=r"^https?://", max_length=2048
    )
    address_raw: str = Field(
        ..., description="Full address as a single string", max_length=500
    )
    number: int = Field(..., description="Street number")
    street_name: str = Field(..., description="Street name", max_length=200)
    city: str = Field(..., description="City", max_length=100)
    state: str = Field(..., description="State", max_length=50)
    zip_code: str = Field(..., description="ZIP code", max_length=20)
    latitude: float = Field(..., description="Latitude coordinate", ge=-90, le=90)
    longitude: float = Field(..., description="Longitude coordinate", ge=-180, le=180)


class LocationUpdate(BaseModel):
    """Request schema for partially updating a happy hour location.

    Only fields explicitly set in the request body are applied.
    """

    name: Optional[str] = Field(None, description="Name of the venue", max_length=200)
    url: Optional[str] = Field(
        None, description="Website URL", pattern=r"^https?://", max_length=2048
    )
    address_raw: Optional[str] = Field(
        None, description="Full address as a single string", max_length=500
    )
    number: Optional[int] = Field(None, description="Street number")
    street_name: Optional[str] = Field(None, description="Street name", max_length=200)
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State", max_length=50)
    zip_code: Optional[str] = Field(None, description="ZIP code", max_length=20)
    latitude: Optional[float] = Field(
        None, description="Latitude coordinate", ge=-90, le=90
    )
    longitude: Optional[float] = Field(
        None, description="Longitude coordinate", ge=-180, le=180
    )
    closed: Optional[bool] = Field(None, description="Whether the location is closed")
    illegal: Optional[bool] = Field(None, description="Whether the location is illegal")


class LocationResponse(BaseModel):
    """Response schema representing a happy hour location."""

    id: int
    name: str
    closed: bool
    illegal: bool
    url: Optional[str]
    address_raw: str
    number: int
    street_name: str
    city: str
    state: str
    zip_code: str
    latitude: float
    longitude: float

    @staticmethod
    def from_model(loc: Any) -> "LocationResponse":
        """Build a :class:`LocationResponse` from a database location entity.

        :param loc: A :class:`Location` ORM instance.
        :returns: A populated response model.
        :rtype: LocationResponse
        """
        return LocationResponse(
            id=loc.id,
            name=loc.Name,
            closed=loc.Closed,
            illegal=loc.Illegal,
            url=loc.URL,
            address_raw=loc.AddressRaw,
            number=loc.Number,
            street_name=loc.StreetName,
            city=loc.City,
            state=loc.State,
            zip_code=loc.ZipCode,
            latitude=loc.Latitude,
            longitude=loc.Longitude,
        )


class EventCreate(BaseModel):
    """Request schema for scheduling a new happy hour event."""

    location_id: int = Field(..., description="ID of the location for the event")
    description: Optional[str] = Field(
        None, description="Optional description of the event", max_length=1000
    )
    when: datetime = Field(..., description="Date/time of the event")

    @field_validator("when")
    @classmethod
    def when_must_be_in_future(cls, v: datetime) -> datetime:
        """Reject event dates that are in the past."""
        now = datetime.now(UTC)
        # Make naive datetimes comparable by treating them as UTC
        compare = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        if compare < now:
            raise ValueError("Event date must be in the future")
        return v


class EventResponse(BaseModel):
    """Response schema representing a happy hour event."""

    id: int
    description: Optional[str]
    when: datetime
    location_id: int
    location_name: str
    location_url: Optional[str] = None
    location_address: Optional[str] = None
    tyrant_username: Optional[str]
    auto_selected: bool
    current_tyrant_username: Optional[str] = None
    current_tyrant_deadline: Optional[datetime] = None


class RotationMemberResponse(BaseModel):
    """Response schema for a single member in a rotation schedule."""

    position: int = Field(..., description="Position in the rotation (0-based)")
    username: str = Field(..., description="Username of the rotation member")
    status: str = Field(
        ..., description="Assignment status (scheduled/pending/chosen/missed)"
    )
    deadline: Optional[datetime] = Field(
        None, description="Deadline for picking, if activated"
    )


class RotationScheduleResponse(BaseModel):
    """Response schema for the full rotation schedule of a cycle."""

    cycle: int = Field(..., description="Cycle number")
    members: list[RotationMemberResponse] = Field(
        ..., description="Ordered list of rotation members"
    )


class PaginatedEventResponse(BaseModel):
    """Paginated wrapper for event responses."""

    items: list[EventResponse] = Field(..., description="Page of event items")
    total: int = Field(..., description="Total number of items across all pages")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Maximum items per page")


class PaginatedLocationResponse(BaseModel):
    """Paginated wrapper for location responses."""

    items: list[LocationResponse] = Field(..., description="Page of location items")
    total: int = Field(..., description="Total number of items across all pages")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Maximum items per page")
