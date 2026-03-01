"""Registration OIDC login initiation endpoint."""

from typing import Annotated

from fastapi import Query, Request
from starlette.responses import RedirectResponse

from models import ExternalAuthProvider
from ratelimit import limiter

from .login import _validate_redirect
from .router import Authentication, AuthMgrs


@Authentication.get(
    "/register/{provider}",
    summary="Start OIDC registration flow",
    description="Redirects the user to the OIDC provider's authorization endpoint "
                "to begin a new account registration. Only new users should use "
                "this endpoint; existing users should use /login/{provider} instead.",
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    provider: ExternalAuthProvider,
    scopes: Annotated[str, Query()] = "openid email profile",
    redirect: Annotated[str, Query()] = "/api/v2/account/profile",
) -> RedirectResponse:
    """Start an OIDC registration flow for the given provider.

    :param request: The incoming :class:`Request`.
    :param provider: The external auth provider to register with.
    :param scopes: Space-separated OAuth2 scopes to request.
    :param redirect: Relative URL to redirect to after successful
        registration.  Absolute URLs are rejected.
    :returns: A redirect response to the provider's authorisation endpoint.
    :rtype: RedirectResponse
    :raises ~fastapi.HTTPException: If *redirect* is not a relative path.
    """
    _validate_redirect(redirect)
    auth = AuthMgrs[provider.name]
    scopes_list = set(scopes.split(' '))
    return await auth.login(redirect, scopes_list, mode="register")
