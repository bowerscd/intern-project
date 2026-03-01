"""Health check endpoint — unauthenticated liveness and readiness probe."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .shared import DatabaseRaw

logger = logging.getLogger(__name__)

Health = APIRouter(tags=["Health"])


@Health.get(
    "/healthz",
    summary="Liveness / readiness probe",
    response_class=JSONResponse,
)
async def healthcheck() -> JSONResponse:
    """Return application health including database and scheduler status.

    Returns ``200`` when the application, database, and scheduler are
    healthy, or ``503`` when any component is unhealthy.

    :returns: JSON body with ``status``, ``db``, and ``scheduler`` keys.
    :rtype: JSONResponse
    """
    db_ok = False
    try:
        session = DatabaseRaw.session()
        with session:
            session.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)

    scheduler_ok = False
    try:
        from scheduler import get_scheduler

        sched = get_scheduler()
        scheduler_ok = sched.running
    except Exception:
        logger.warning("Health check: scheduler unavailable", exc_info=True)

    healthy = db_ok and scheduler_ok
    body: dict[str, Any] = {
        "status": "ok" if healthy else "degraded",
        "db": "ok" if db_ok else "unreachable",
        "scheduler": "ok" if scheduler_ok else "stopped",
    }
    return JSONResponse(content=body, status_code=200 if healthy else 503)
