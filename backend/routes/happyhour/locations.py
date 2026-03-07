"""
Happy Hour location endpoints — authenticated, require HAPPY_HOUR claim.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status, Query

from routes.shared import Database, RequireLogin, require_write_access
from models import AccountClaims
from csrf import validate_csrf_token

from schemas.happyhour import (
    LocationCreate,
    LocationUpdate,
    LocationResponse,
    PaginatedLocationResponse,
)

from .router import HappyHour


@HappyHour.get(
    "/locations",
    summary="List all happy hour locations",
    description="Get all happy hour locations with pagination. Requires HAPPY_HOUR claim.",
    response_model=PaginatedLocationResponse,
)
async def list_locations(
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> PaginatedLocationResponse:
    """Return a paginated list of happy hour locations.

    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :param page: Page number (1-based).
    :param page_size: Maximum number of items per page (1-100).
    :returns: A :class:`PaginatedLocationResponse` with the requested page.
    :rtype: PaginatedLocationResponse
    """
    from db.functions import get_locations_paginated, count_locations

    with db:
        total = count_locations(db)
        offset = (page - 1) * page_size
        locations = get_locations_paginated(db, offset, page_size)

        return PaginatedLocationResponse(
            items=[LocationResponse.from_model(loc) for loc in locations],
            total=total,
            page=page,
            page_size=page_size,
        )


@HappyHour.post(
    "/locations",
    summary="Submit a new happy hour location",
    dependencies=[Depends(validate_csrf_token)],
    description="Create a new happy hour location. Requires HAPPY_HOUR claim.",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    body: LocationCreate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> LocationResponse:
    """Create a new happy hour location.

    :param body: The location creation payload.
    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :returns: The newly created :class:`LocationResponse`.
    :rtype: LocationResponse
    """
    require_write_access(account)

    from db.functions import create_location as db_create_location

    with db:
        loc = db_create_location(
            db,
            Name=body.name,
            URL=body.url,
            AddressRaw=body.address_raw,
            Number=body.number,
            StreetName=body.street_name,
            City=body.city,
            State=body.state,
            ZipCode=body.zip_code,
            Latitude=body.latitude,
            Longitude=body.longitude,
        )
        db.commit()

        return LocationResponse.from_model(loc)


@HappyHour.get(
    "/locations/{location_id}",
    summary="Get a specific location",
    description="Get a happy hour location by ID. Requires HAPPY_HOUR claim.",
    response_model=LocationResponse,
)
async def get_location(
    location_id: int,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR))],
    db: Database,
) -> LocationResponse:
    """Return a specific happy hour location by ID.

    :param location_id: The location's integer ID.
    :param account: The authenticated account with ``HAPPY_HOUR`` claim.
    :param db: Active database session.
    :returns: The matching :class:`LocationResponse`.
    :rtype: LocationResponse
    :raises HTTPException: If the location is not found.
    """
    from db.functions import get_location_by_id

    with db:
        loc = get_location_by_id(db, location_id)

        if loc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found",
            )

        return LocationResponse.from_model(loc)


@HappyHour.patch(
    "/locations/{location_id}",
    summary="Update a happy hour location",
    dependencies=[Depends(validate_csrf_token)],
    description="Update a location (e.g., mark as closed). Requires HAPPY_HOUR_TYRANT claim.",
    response_model=LocationResponse,
)
async def update_location(
    location_id: int,
    body: LocationUpdate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.HAPPY_HOUR_TYRANT))],
    db: Database,
) -> LocationResponse:
    """Update an existing happy hour location.

    :param location_id: The location's integer ID.
    :param body: The partial update payload.
    :param account: The authenticated account with ``HAPPY_HOUR_TYRANT``
        claim.
    :param db: Active database session.
    :returns: The updated :class:`LocationResponse`.
    :rtype: LocationResponse
    :raises HTTPException: If the location is not found.
    """
    require_write_access(account)

    from db.functions import get_location_by_id

    with db:
        loc = get_location_by_id(db, location_id)
        if loc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Location not found",
            )

        update_data = body.model_dump(exclude_unset=True)
        field_mapping = {
            "name": "Name",
            "url": "URL",
            "address_raw": "AddressRaw",
            "number": "Number",
            "street_name": "StreetName",
            "city": "City",
            "state": "State",
            "zip_code": "ZipCode",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "closed": "Closed",
            "illegal": "Illegal",
        }

        for pydantic_field, db_field in field_mapping.items():
            if pydantic_field in update_data:
                setattr(loc, db_field, update_data[pydantic_field])

        db.commit()
        db.refresh(loc)

        return LocationResponse.from_model(loc)
