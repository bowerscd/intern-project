"""Top-level route configuration and OpenAPI tag definitions."""

from .tags import ApiTags, SESSION_COOKIE_NAME
from .account import Accounts
from .auth import Authentication
from .happyhour import HappyHour
from .mealbot import Mealbot

__all__ = [
    "ApiTags",
    "SESSION_COOKIE_NAME",
    "Mealbot",
    "Authentication",
    "HappyHour",
    "Accounts",
]
