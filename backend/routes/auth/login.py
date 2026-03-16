"""OIDC login initiation endpoint."""

import logging
from typing import Annotated
from urllib.parse import urlparse

from fastapi import HTTPException, Query, Request, status
from starlette.responses import RedirectResponse

from config import AUTH_REDIRECT_ORIGINS
from models import ExternalAuthProvider
from ratelimit import limiter

from .router import Authentication, AuthMgrs

logger = logging.getLogger(__name__)


def _validate_redirect(redirect: str) -> str:
    """Validate that *redirect* is safe to use as a post-authentication target.

    Accepts relative paths unconditionally.  Absolute URLs are allowed
    only when their origin (scheme + host) appears in
    :data:`~config.AUTH_REDIRECT_ORIGINS`.

    :param redirect: The candidate redirect URL.
    :returns: The validated redirect string.
    :rtype: str
    :raises ~fastapi.HTTPException: If the redirect is an unrecognised
        absolute URL.
    """
    if "\\" in redirect:
        logger.warning("Redirect validation failed: backslash in redirect=%r", redirect)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect contains invalid characters",
        )
    parsed = urlparse(redirect)
    if parsed.scheme or parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in AUTH_REDIRECT_ORIGINS:
            logger.warning(
                "Redirect validation failed: origin=%r not in allow-list", origin
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect origin is not in the allow-list",
            )
    return redirect


@Authentication.get(
    "/login/{provider}",
    summary="Start OIDC login flow",
    description="Redirects the user to the OIDC provider's authorization endpoint. "
    "Only 'google' provider is supported for production use.",
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    provider: ExternalAuthProvider,
    scopes: Annotated[str, Query()] = "openid email profile",
    redirect: Annotated[str, Query()] = "/api/v2/account/profile",
) -> RedirectResponse:
    """Start an OIDC login flow for the given provider.

    :param request: The incoming :class:`Request`.
    :param provider: The external auth provider to authenticate with.
    :param scopes: Space-separated OAuth2 scopes to request.
    :param redirect: Relative URL to redirect to after successful
        authentication.  Absolute URLs are rejected.
    :returns: A redirect response to the provider's authorisation endpoint.
    :rtype: RedirectResponse
    :raises ~fastapi.HTTPException: If *redirect* is not a relative path.
    """
    _validate_redirect(redirect)
    auth = AuthMgrs[provider.name]
    scopes_list = set(scopes.split(" "))
    return await auth.login(redirect, scopes_list)
