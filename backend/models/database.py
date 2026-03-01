"""SQLAlchemy declarative base model."""

from sqlalchemy.orm import DeclarativeBase


class Model(DeclarativeBase):
    """Base declarative model for all SQLAlchemy ORM entities.

    All database table models inherit from this class, which provides
    the SQLAlchemy declarative mapping infrastructure.
    """

    pass
