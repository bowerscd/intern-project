"""Authentication package — OIDC handler and config."""

from .base import AuthenticationHandler
from .config import AuthConfig as Config

__all__ = [
    "AuthenticationHandler",
    "Config"
]
