"""Account router instance.

Extracted from :mod:`routes.account` to break the circular import between
the package ``__init__`` and its sub-modules (``profile``, ``claims``),
which decorate endpoints onto this router.
"""

from fastapi import APIRouter

from routes.tags import ApiTags
from routes.shared import database_lifespan

Accounts: APIRouter = APIRouter(
    tags=[ApiTags.Accounts],
    prefix='/api/v2/account',
    lifespan=database_lifespan,
)
