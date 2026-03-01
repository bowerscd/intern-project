"""OIDC callback endpoint — token exchange and session establishment."""

from typing import Annotated, Tuple

from fastapi import Cookie, HTTPException, Query, Request, status
from starlette.responses import RedirectResponse
from pydantic import BaseModel

from sqlalchemy import Row

from models import (
    DBAccount as Account,
    ExternalAuthProvider,
)

from routes.shared import Database, AUTH_SESSION_KEY
from ratelimit import limiter

PENDING_REGISTRATION_KEY = "pending_registration"

from .router import Authentication, AuthMgrs


class AuthenticateCookies(BaseModel):
    """Expected cookies on an OIDC callback request."""

    auth_state: str
    auth_nonce: str


class AuthenticationQuery(BaseModel):
    """Expected query parameters on an OIDC callback request."""

    code: str
    state: str


@Authentication.get(
    "/callback/{provider}",
    summary="OIDC callback",
    description="Handles the OIDC provider callback. Exchanges the authorization code "
                "for tokens, verifies the id_token, and routes to login or registration "
                "based on the mode encoded in the OAuth state parameter.",
)
@limiter.limit("20/minute")
async def authenticate(
    request: Request,
    provider: ExternalAuthProvider,
    cookies: Annotated[AuthenticateCookies, Cookie()],
    query: Annotated[AuthenticationQuery, Query()],
    db: Database,
) -> RedirectResponse:
    """Handle the OIDC provider callback.

    Exchanges the authorisation code for tokens, verifies the ID token,
    and routes to login or registration based on the mode encoded in the
    OAuth state parameter.

    **Login mode** — looks up the account by provider+sub and establishes
    a session.

    **Register mode** — stores the OIDC identity in
    ``session["pending_registration"]`` so the user can choose a
    username via ``POST /complete-registration`` or claim an existing
    account via ``POST /claim-account``.

    :param request: The incoming :class:`Request`.
    :param provider: The external auth provider that issued the callback.
    :param cookies: Anti-CSRF cookies attached to the request.
    :param query: Query parameters including the authorisation code.
    :param db: Active database session.
    :returns: A redirect response to the post-authentication target.
    :rtype: RedirectResponse
    :raises HTTPException: On missing account (login) or already-registered
        provider (register).
    """
    auth = AuthMgrs[provider.name]
    redirect, identity = await auth.authenticate(cookies.model_dump(), query.model_dump())

    if not isinstance(identity.get('id'), dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication failed",
        )

    uuid = identity['id']['sub']
    mode = identity.get('mode', 'login')

    act: Row[Tuple[Account]] | None | Account | Tuple[Account]

    with db:
        from db.functions import get_account_by_provider

        act = get_account_by_provider(db, provider, uuid)

        if mode == "register":
            if act is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Account already registered. Please log in.",
                )
            # Regenerate session to prevent session fixation
            request.session.clear()
            # Store the OIDC identity needed for registration and account claims
            request.session[PENDING_REGISTRATION_KEY] = {
                "provider": provider.name,
                "sub": uuid,
                "name": identity["id"].get("name", ""),
                "email": identity["id"].get("email"),
            }
            return redirect
        else:
            # mode == "login" (default)
            if act is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Authentication failed.",
                )

            if not isinstance(act, Account):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="authentication failed",
                )

            # Regenerate session to prevent session fixation
            request.session.clear()
            request.session[AUTH_SESSION_KEY] = act.id

    return redirect
