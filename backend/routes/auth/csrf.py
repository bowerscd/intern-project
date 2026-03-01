"""GET /csrf-token — return a CSRF token for use in state-changing requests."""

from fastapi import Request

from csrf import ensure_csrf_token

from .router import Authentication


@Authentication.get(
    "/csrf-token",
    summary="Get CSRF token",
    description="Return a CSRF token that must be included in the "
                "X-CSRF-Token header on all POST, PATCH, PUT, and DELETE requests.",
)
async def get_csrf_token(request: Request) -> dict:
    """Generate or retrieve the session's CSRF token.

    The token is stored in the session cookie and must be sent back
    in the ``X-CSRF-Token`` header on mutating requests.

    :param request: The incoming :class:`Request`.
    :returns: A dict containing the CSRF token.
    :rtype: dict
    """
    token = ensure_csrf_token(request)
    return {"csrf_token": token}
