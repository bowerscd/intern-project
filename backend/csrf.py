"""CSRF protection using the synchronizer token pattern.

Generates a random CSRF token, stores it in the session, and validates
it on state-changing requests via the ``X-CSRF-Token`` header.

Usage::

    from csrf import validate_csrf_token

    @router.post("/endpoint", dependencies=[Depends(validate_csrf_token)])
    async def my_endpoint(...): ...
"""

import secrets

from fastapi import HTTPException, Request, status

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


def ensure_csrf_token(request: Request) -> str:
    """Ensure a CSRF token exists in the session and return it.

    If no token is present, a new cryptographically random token is
    generated, stored in the session, and returned.

    :param request: The incoming :class:`Request`.
    :returns: The CSRF token string.
    :rtype: str
    """
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def validate_csrf_token(request: Request) -> None:
    """Validate that the CSRF header matches the session token.

    Should be used as a FastAPI dependency on all state-changing
    (POST, PATCH, PUT, DELETE) endpoints.

    :param request: The incoming :class:`Request`.
    :raises HTTPException: If the CSRF token is missing or does not match.
    """
    session_token = request.session.get(CSRF_SESSION_KEY)
    header_token = request.headers.get(CSRF_HEADER)

    if not session_token or not header_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing",
        )

    if not secrets.compare_digest(session_token, header_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch",
        )
