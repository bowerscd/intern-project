"""Mealbot router — v0, v1, and v2 meal-credit endpoints."""

from fastapi import APIRouter

from routes.tags import ApiTags
from routes.shared import database_lifespan
from .v0 import MealbotV0
from .v1 import MealbotV1
from .v2 import MealbotV2


Mealbot: APIRouter = APIRouter(
    tags=[ApiTags.Mealbot], prefix="/api", lifespan=database_lifespan
)

Mealbot.include_router(MealbotV0)
Mealbot.include_router(MealbotV1)
Mealbot.include_router(MealbotV2)

__all__ = ["Mealbot"]
