"""Happy hour location ORM model."""

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Model


class Location(Model):
    """Happy hour venue persisted in the ``HappyHourLocations`` table.

    Stores the name, address, geo-coordinates, and operational status
    of each venue.
    """

    __tablename__ = "HappyHourLocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    Name: Mapped[str] = mapped_column(String())
    Closed: Mapped[bool] = mapped_column(default=False)
    Illegal: Mapped[bool] = mapped_column(default=False)
    URL: Mapped[Optional[str]] = mapped_column(String(), nullable=True)

    # Location Information
    AddressRaw: Mapped[str] = mapped_column(String())
    Number: Mapped[int] = mapped_column()
    StreetName: Mapped[str] = mapped_column(String())
    City: Mapped[str] = mapped_column(String())
    State: Mapped[str] = mapped_column(String())
    ZipCode: Mapped[str] = mapped_column(String())

    Latitude: Mapped[float] = mapped_column()
    Longitude: Mapped[float] = mapped_column()

    def __repr__(self) -> str:
        """Return a developer-friendly string representation of the location.

        :returns: A string showing the location name.
        :rtype: str
        """
        return f"<HappyHourLocation {self.Name}>"
