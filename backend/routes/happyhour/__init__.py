"""Happy hour router — event and location endpoints."""

from .events import *  # noqa: F403 — registers endpoints on HappyHour router
from .locations import *  # noqa: F403 — registers endpoints on HappyHour router
from .router import HappyHour

__all__ = ["HappyHour"]
