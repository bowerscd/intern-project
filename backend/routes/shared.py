"""Shared route utilities — database dependency, auth guards, and helpers."""

from collections.abc import AsyncIterator, Generator
from functools import wraps
from typing import Annotated, Any
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Request, HTTPException, status, Depends, APIRouter
from fastapi.security import APIKeyCookie

from . import SESSION_COOKIE_NAME

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import Database as _Database
from models import AccountClaims, DBAccount as Account

DatabaseRaw = _Database()

Database = Annotated[Session, Depends(DatabaseRaw.session)]

AUTH_SESSION_KEY = "current_user"


def reject_if_legacy_disabled(fn: Any) -> Any:
    """Decorator that **unconditionally** returns ``410 Gone``.

    Legacy v0/v1 endpoints are permanently disabled.  The original route
    handler code is preserved for historical reference but is never
    invoked.

    Also marks the wrapped endpoint with a ``_legacy_endpoint`` sentinel
    so that :func:`mark_legacy_routes_deprecated` can flag it in the
    OpenAPI schema.

    :param fn: The route handler to wrap.
    :returns: The wrapped handler.
    :rtype: Any
    """

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Reject the request unconditionally — legacy endpoints are permanently disabled.

        :param args:   Positional arguments (unused).
        :param kwargs: Keyword arguments (unused).
        :raises ~fastapi.HTTPException: Always raises ``410 Gone``.
        """
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="legacy endpoints are permanently disabled; use /api/v2",
        )

    wrapper._legacy_endpoint = True  # sentinel for mark_legacy_routes_deprecated
    return wrapper


def mark_legacy_routes_deprecated(router: APIRouter) -> None:
    """Mark every legacy route on *router* as deprecated in the OpenAPI schema.

    Legacy v0/v1 routes are permanently disabled and always return
    ``410 Gone``.  This function annotates them as *deprecated* in the
    OpenAPI schema so clients see the status in generated documentation.

    A route is considered legacy if its endpoint callable has a
    ``_legacy_endpoint`` sentinel attribute (set by
    :func:`reject_if_legacy_disabled`).

    :param router: The :class:`APIRouter` whose routes should be
        inspected.
    """
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if callable(endpoint) and getattr(endpoint, "_legacy_endpoint", False):
            route.deprecated = True


@asynccontextmanager
async def database_lifespan(app: APIRouter) -> AsyncIterator[None]:
    """Shared lifespan context manager that starts and stops the database.

    :param app: The :class:`APIRouter` triggering the lifespan events.
    """
    with DatabaseRaw:
        yield


def resolve_summary(
    db: Session,
    user: str | None,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    """Resolve a meal-credit summary request.

    Shared between v1 and v2 route handlers.  Returns either a global
    summary or a per-user summary, optionally filtered by time range.

    :param db: Active database session.
    :param user: Username to filter by, or ``None`` for a global summary.
    :param start: Inclusive lower time bound, or ``None``.
    :param end: Inclusive upper time bound, or ``None``.
    :returns: A dict representing the credit summary.
    :rtype: dict[str, Any]
    :raises HTTPException: If only one of *start*/*end* is provided, or
        if the user does not exist.
    """
    from db.functions import (
        get_global_summary,
        get_summary_for_user,
    )

    if (start is None) != (end is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start and end must both be provided or both omitted",
        )

    try:
        if user is None:
            return get_global_summary(db)
        elif start is not None and end is not None:
            return get_summary_for_user(db, user, start, end)
        else:
            return get_summary_for_user(db, user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


class RequireLogin:
    """FastAPI dependency that validates session authentication and claims.

    Usage::

        Depends(RequireLogin(AccountClaims.MEALBOT))

    Yields the authenticated :class:`Account` if the session is valid and
    the account possesses the required claim.
    """

    def __init__(self, required_claim: AccountClaims) -> None:
        """Initialise the dependency with a required claim.

        :param required_claim: The :class:`AccountClaims` flag the
            authenticated user must have.
        """
        self.__required_claim = required_claim

    def __call__(
            self,
            request: Request,
            db: Database,
            _: Any = Depends(APIKeyCookie(name=SESSION_COOKIE_NAME)),
    ) -> Generator[Account, None, None]:
        """Validate the session cookie and yield the authenticated account.

        :param request: The incoming :class:`Request`.
        :param db: Active database session (injected).
        :param _: Session cookie value (validated by FastAPI).
        :yields: The authenticated :class:`Account` instance.
        :raises HTTPException: If the session is missing, the account is
            not found, or the account lacks the required claim.
        """
        id = request.session.get(AUTH_SESSION_KEY)
        if id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not authenticated",
            )
        act: Account

        with db:
            act = db.scalars(select(Account).where(Account.id == id)).first()
            if act is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="account not found",
                )

            if act.claims & self.__required_claim != self.__required_claim:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="insufficient permissions"
                )

            yield act
