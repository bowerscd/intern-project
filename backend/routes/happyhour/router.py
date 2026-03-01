"""Happy hour router instance.

Extracted from :mod:`routes.happyhour` to break the circular import between
the package ``__init__`` and its sub-modules (``locations``, ``events``),
which decorate endpoints onto this router.
"""

from fastapi import APIRouter

from routes.tags import ApiTags
from routes.shared import database_lifespan

HappyHour: APIRouter = APIRouter(
    tags=[ApiTags.HappyHour],
    prefix='/api/v2/happyhour',
    lifespan=database_lifespan,
)
