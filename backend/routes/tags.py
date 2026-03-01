"""OpenAPI tag definitions and session cookie name.

Extracted from :mod:`routes` to break the circular import between
the top-level ``routes`` package and its sub-packages, which need
``ApiTags`` at import time.
"""

from enum import StrEnum, auto

from server import hostname

SESSION_COOKIE_NAME: str = f"{hostname()}.session"


class ApiTags(StrEnum):
    """OpenAPI tag names used to group API endpoints in documentation."""

    Mealbot = auto()
    HappyHour = auto()
    Authentication = auto()
    Accounts = auto()
    Legacy = auto()
