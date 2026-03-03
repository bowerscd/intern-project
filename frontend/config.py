"""Frontend configuration with environment variable support and smart defaults."""

import os
import socket
from typing import Any


def _get(env_var: str, default: Any = None) -> Any:
    """Get config value from environment variable or fall back to default.

    :param env_var: Environment variable name.
    :param default: Value returned when env var is not set.
    :returns: The resolved configuration value.
    """
    val = os.environ.get(env_var)
    if val is not None:
        return val
    return default


def _get_bool(env_var: str, default: bool = False) -> bool:
    """Get boolean config value from environment variable.

    :param env_var: Environment variable name.
    :param default: Default boolean value.
    :returns: True if env var is "true", "1", or "yes" (case-insensitive).
    """
    val = os.environ.get(env_var)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Public configuration attributes
# ---------------------------------------------------------------------------

DEV_MODE: bool = _get_bool("DEV", False)
"""Whether the application is running in development mode."""

SERVER_HOSTNAME: str = _get("SERVER_HOSTNAME", None) or socket.gethostname()
"""The public-facing server hostname (defaults to OS hostname)."""

BACKEND_HOSTNAME: str = _get("BACKEND_HOSTNAME", "backend")
"""The internal Docker hostname for the backend service."""

USE_MOCK: bool = _get_bool("USE_MOCK", False)
"""Whether to use mock mode (disables auth gate, mocks API calls)."""

USE_PROXY: bool = _get_bool("USE_PROXY", True)
"""Whether to proxy /api/* requests to the backend (recommended)."""
