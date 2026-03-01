"""Account router — profile, claims management, and admin endpoints."""

from .admin import *  # noqa: F403 — registers admin endpoints on Accounts router
from .claims import *  # noqa: F403 — registers endpoints on Accounts router
from .profile import *  # noqa: F403 — registers endpoints on Accounts router
from .router import Accounts

__all__ = [
    "Accounts"
]
