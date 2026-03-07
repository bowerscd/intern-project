"""FastAPI application entry point and middleware configuration."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from config import (
    DEV_MODE,
    SESSION_SECRET,
    CORS_ALLOW_ORIGINS,
    SESSION_COOKIE_DOMAIN,
    SESSION_SAME_SITE,
)
from server import hostname
from logging_config import setup_logging
from ratelimit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from middleware import RequestLoggingMiddleware
from routes import SESSION_COOKIE_NAME, Mealbot, Accounts, HappyHour, Authentication
from routes.health import Health

setup_logging()
logger = logging.getLogger(__name__)

secret = SESSION_SECRET

# Dev-mode admin account constants
DEV_ADMIN_SUB = "dev-admin"
DEV_ADMIN_USERNAME = "admin"
DEV_ADMIN_EMAIL = "admin@dev.local"


def _seed_dev_admin(db: "Database") -> None:  # noqa: F821
    """Create a pre-activated admin account for local development.

    Uses a well-known OIDC ``sub`` (``dev-admin``) so that logging in
    via the mock OIDC provider with that sub grants admin access
    immediately — no manual ``sqlite3`` promotion needed.

    Skipped silently if the account already exists.
    """
    from sqlalchemy import select
    from models import (
        DBAccount as Account,
        AccountClaims,
        AccountStatus,
        ExternalAuthProvider,
    )

    with db.session() as session:
        existing = session.execute(
            select(Account).where(Account.username == DEV_ADMIN_USERNAME)
        ).scalar_one_or_none()
        if existing is not None:
            return

        admin = Account(
            username=DEV_ADMIN_USERNAME,
            email=DEV_ADMIN_EMAIL,
            account_provider=ExternalAuthProvider.test,
            external_unique_id=DEV_ADMIN_SUB,
            claims=AccountClaims.BASIC | AccountClaims.ADMIN,
            status=AccountStatus.ACTIVE,
        )
        session.add(admin)
        session.commit()
        logger.info(
            "Dev admin account seeded: username=%s, sub=%s",
            DEV_ADMIN_USERNAME,
            DEV_ADMIN_SUB,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage the application lifecycle — start and stop the scheduler.

    :param app: The :class:`FastAPI` application instance.
    """
    from scheduler import start_scheduler, stop_scheduler
    from routes.shared import DatabaseRaw

    DatabaseRaw.start()  # Balanced by stop() in teardown

    if DEV_MODE:
        _seed_dev_admin(DatabaseRaw)

    try:
        start_scheduler()
    except Exception:
        if DEV_MODE:
            logger.warning(
                "Scheduler failed to start (may be expected in test environments)",
                exc_info=True,
            )
        else:
            logger.critical("Scheduler failed to start in production", exc_info=True)
            raise

    yield

    try:
        stop_scheduler()
    except Exception:
        pass

    try:
        DatabaseRaw.stop()
    except Exception:
        logger.warning("Database shutdown error", exc_info=True)


app = FastAPI(
    title=f"Mealbot API — api.{hostname()}",
    description="FastAPI backend for Mealbot meal tracking and Happy Hour coordination. "
    "v0/v1 endpoints are permanently disabled and always return 410 Gone. "
    "v2 endpoints require Google OIDC authentication.",
    version="2.0.0",
    debug=DEV_MODE,
    lifespan=lifespan,
    docs_url="/docs" if DEV_MODE else None,
    redoc_url="/redoc" if DEV_MODE else None,
    openapi_url="/openapi.json" if DEV_MODE else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Global exception handler ──────────────────────────────────────────


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitised 500 response for unhandled exceptions.

    In dev mode, the traceback is included in the response body.
    """
    from middleware import request_id_var

    rid = request_id_var.get()

    # Extract as much context as possible for post-mortem debugging
    account_id: int | None = None
    try:
        account_id = request.session.get("account_id")
    except Exception:
        pass

    client_ip = request.client.host if request.client else None
    forwarded_for = request.headers.get("x-forwarded-for")
    user_agent = request.headers.get("user-agent", "")

    logger.exception(
        "Unhandled exception on %s %s [rid=%s user=%s ip=%s]: %s",
        request.method,
        request.url.path,
        rid,
        account_id,
        forwarded_for or client_ip,
        type(exc).__qualname__,
        extra={
            "action": "unhandled_exception",
            "http_method": request.method,
            "http_path": request.url.path,
            "http_query": str(request.url.query) if request.url.query else None,
            "account_id": account_id,
            "client_ip": forwarded_for or client_ip,
            "user_agent": user_agent,
            "exception_type": type(exc).__qualname__,
        },
    )
    content: dict = {"detail": "Internal server error"}
    if rid:
        content["request_id"] = rid
    if DEV_MODE:
        import traceback

        content["traceback"] = traceback.format_exception(exc)
    return JSONResponse(status_code=500, content=content)


# ── Middleware (outermost listed last — Starlette wraps LIFO) ─────────

app.add_middleware(
    SessionMiddleware,
    secret_key=secret,
    same_site=SESSION_SAME_SITE,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=60 * 30,
    https_only=not DEV_MODE,
    domain=SESSION_COOKIE_DOMAIN,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Cookie",
        "X-Request-ID",
        "X-CSRF-Token",
    ],
)

app.add_middleware(GZipMiddleware, minimum_size=500)

# Request logging — outermost so it captures the full request lifecycle
app.add_middleware(RequestLoggingMiddleware)

# In production, restrict trusted proxy hosts; in dev, trust all.
if DEV_MODE:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
else:
    import os as _os

    _trusted = [
        h.strip()
        for h in _os.environ.get("TRUSTED_PROXY_HOSTS", "127.0.0.1").split(",")
        if h.strip()
    ]
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted)

# ── Routers ───────────────────────────────────────────────────────────

app.include_router(Health)
app.include_router(Mealbot)
app.include_router(Authentication)
app.include_router(HappyHour)
app.include_router(Accounts)
