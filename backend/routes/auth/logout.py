"""POST /logout — destroy the authenticated session."""

from fastapi import Depends, Request, status
from starlette.responses import JSONResponse

from csrf import validate_csrf_token
from ratelimit import limiter

from .router import Authentication


@Authentication.post(
    "/logout",
    summary="Logout",
    description="Destroy the current session and clear the session cookie.",
    dependencies=[Depends(validate_csrf_token)],
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def logout(request: Request) -> JSONResponse:
    """Clear the session to log the user out.

    :param request: The incoming :class:`Request`.
    :returns: A JSON acknowledgement.
    :rtype: JSONResponse
    """
    request.session.clear()
    return JSONResponse(content={"detail": "logged out"})
