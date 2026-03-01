"""Authentication router — OIDC login, registration, callback, claiming, and CSRF."""

from .authenticate import *  # noqa: F403 — registers endpoints on Authentication router
from .claim_account import *  # noqa: F403 — registers endpoints on Authentication router
from .complete_registration import *  # noqa: F403 — registers endpoints on Authentication router
from .csrf import *  # noqa: F403 — registers CSRF token endpoint on Authentication router
from .login import *  # noqa: F403 — registers endpoints on Authentication router
from .logout import *  # noqa: F403 — registers endpoints on Authentication router
from .register import *  # noqa: F403 — registers endpoints on Authentication router
from .router import Authentication, AuthMgrs

__all__ = [
    "Authentication",
    "AuthMgrs",
]
