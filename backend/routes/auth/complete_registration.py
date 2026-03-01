"""POST /complete-registration — finish OIDC registration with chosen username."""

from fastapi import Depends, HTTPException, Request, status

from sqlalchemy.exc import IntegrityError

from csrf import validate_csrf_token
from db.functions import create_account
from models import AccountClaims, ExternalAuthProvider
from routes.shared import Database, AUTH_SESSION_KEY
from schemas.account import CompleteRegistrationRequest
from ratelimit import limiter

from .authenticate import PENDING_REGISTRATION_KEY
from .router import Authentication


@Authentication.post(
    "/complete-registration",
    summary="Complete registration",
    dependencies=[Depends(validate_csrf_token)],
    description="After OIDC authentication in register mode, the user picks a "
                "username to finish creating their account.",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def complete_registration(
    request: Request,
    body: CompleteRegistrationRequest,
    db: Database,
) -> dict:
    """Create a new account with the user-chosen username.

    Reads ``pending_registration`` from the session (set during the
    OIDC callback in register mode), creates the account, and
    establishes a logged-in session.

    :param request: The incoming :class:`Request`.
    :param body: The registration payload containing the desired username.
    :param db: Active database session.
    :returns: A dict with the new account id and username.
    :raises HTTPException: 401 if no pending registration in session,
        409 if the username is already taken.
    """
    pending = request.session.get(PENDING_REGISTRATION_KEY)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No pending registration. Please start the registration flow.",
        )

    provider = ExternalAuthProvider[pending["provider"]]
    sub = pending["sub"]

    with db:
        act = create_account(
            username=body.username,
            email=None,
            account_provider=provider,
            external_unique_id=sub,
            claims=AccountClaims.BASIC,
        )
        try:
            db.add(act)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken.",
            )

        # Regenerate session to prevent session fixation
        request.session.clear()
        request.session[AUTH_SESSION_KEY] = act.id

    return {"id": act.id, "username": act.username}
