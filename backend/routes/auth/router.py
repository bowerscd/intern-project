"""Authentication router instance and provider manager registry.

Extracted from :mod:`routes.auth` to break the circular import between
the package ``__init__`` and its sub-modules (``login``, ``authenticate``,
``register``), which decorate endpoints onto this router and read
:data:`AuthMgrs`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter

from routes.tags import ApiTags
from routes.shared import DatabaseRaw
from models import ExternalAuthProvider
from auth import AuthenticationHandler, Config

AuthMgrs: dict[str, AuthenticationHandler] = {}


@asynccontextmanager
async def _auth_lifespan(app: APIRouter) -> AsyncIterator[None]:
    """Lifespan that initialises :class:`AuthenticationHandler` instances
    for every :class:`ExternalAuthProvider` and manages the database.

    The ``test`` provider is only initialised when :pydata:`DEV_MODE`
    is ``True`` to prevent accidental use in production.

    :param app: The authentication :class:`APIRouter`.
    :type app: APIRouter
    """
    import logging
    from config import DEV_MODE

    _logger = logging.getLogger(__name__)

    for v in ExternalAuthProvider:
        if v.name == "test" and not DEV_MODE:
            _logger.debug("Skipping test OIDC provider in production mode")
            continue
        AuthMgrs[v.name] = AuthenticationHandler(Config(v.config, v.name))
    with DatabaseRaw:
        yield
    for v in list(AuthMgrs):
        del AuthMgrs[v]


Authentication: APIRouter = APIRouter(
    prefix="/api/v2/auth",
    lifespan=_auth_lifespan,
    tags=[ApiTags.Authentication],
)
