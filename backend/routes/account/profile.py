"""
Account profile endpoints — authenticated.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from routes.shared import Database, RequireLogin, require_write_access
from models import AccountClaims
from csrf import validate_csrf_token
from models.enums import PhoneProvider

from schemas.account import ProfileResponse, ProfileUpdate

from .router import Accounts


@Accounts.get(
    "/phone-providers",
    summary="List supported phone carriers",
    description="Returns the names of all supported SMS carrier gateways.",
    response_model=list[str],
)
async def list_phone_providers() -> list[str]:
    """Return all valid :class:`PhoneProvider` member names.

    Used by the frontend to build a carrier dropdown without hardcoding
    the enum values.

    :returns: Sorted list of provider name strings, excluding ``NONE``.
    :rtype: list[str]
    """
    return [p.name for p in PhoneProvider if p != PhoneProvider.NONE]


@Accounts.get(
    "/profile",
    summary="Get user profile",
    description="Get the authenticated user's profile information. Requires BASIC claim.",
    response_model=ProfileResponse,
)
async def get_profile(
    request: Request,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.BASIC))],
) -> ProfileResponse:
    """Return the authenticated user's profile.

    :param request: The incoming :class:`Request`.
    :param account: The authenticated account (injected by
        :class:`RequireLogin`).
    :returns: A :class:`ProfileResponse` for the current user.
    :rtype: ProfileResponse
    """
    return ProfileResponse.from_account(
        account, oidc_email=request.session.get("oidc_email")
    )


@Accounts.patch(
    "/profile",
    summary="Update user profile",
    dependencies=[Depends(validate_csrf_token)],
    description="Update the authenticated user's phone number and carrier for SMS notifications. "
    "Requires BASIC claim.",
    response_model=ProfileResponse,
)
async def update_profile(
    request: Request,
    body: ProfileUpdate,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.BASIC))],
    db: Database,
) -> ProfileResponse:
    """Update the authenticated user's phone and carrier settings.

    :param body: The profile update payload.
    :param account: The authenticated account.
    :param db: Active database session.
    :returns: The updated :class:`ProfileResponse`.
    :rtype: ProfileResponse
    :raises HTTPException: If the account is not found or the phone
        provider is invalid.
    """
    require_write_access(account)
    with db:
        from sqlalchemy import select
        from models import DBAccount as Account

        act = db.scalars(select(Account).where(Account.id == account.id)).first()
        if act is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        if body.username is not None:
            act.username = body.username

        if body.email is not None:
            act.email = body.email or None  # empty string → NULL

        if body.phone is not None:
            act.phone = body.phone

        if body.phone_provider is not None:
            try:
                provider = PhoneProvider[body.phone_provider]
                act.phone_provider = provider
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid phone provider: {body.phone_provider}",
                )

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Determine which unique constraint was violated
            if body.username is not None:
                from sqlalchemy import select as sa_select

                existing = db.scalars(
                    sa_select(Account).where(
                        Account.username == body.username,
                        Account.id != account.id,
                    )
                ).first()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Username is already taken.",
                    )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email address is already in use.",
            )
        db.refresh(act)

        return ProfileResponse.from_account(
            act, oidc_email=request.session.get("oidc_email")
        )


# ── Valid themes ──────────────────────────────────────────────────────

VALID_THEMES = frozenset(
    {
        "default",
        "arachne",
        "daedalus",
        "aphrodite",
        "niflheim",
        "norns",
        "quetzalcoatl",
        "atlas",
        "thoth",
        "yggdrasil",
        "amaterasu",
        "hecate",
        "freya",
        "hermes",
        "prometheus",
        "gaia",
        "skadi",
        "raijin",
        "seshat",
        "hephaestus",
        "vishnu",
        "cernunnos",
        "brigid",
    }
)


@Accounts.get(
    "/themes",
    summary="List available themes",
    description="Returns the names of all available CSS themes.",
    response_model=list[str],
)
async def list_themes() -> list[str]:
    """Return all valid theme names.

    :returns: Sorted list of theme name strings.
    :rtype: list[str]
    """
    return sorted(VALID_THEMES)


@Accounts.put(
    "/theme",
    summary="Set user theme",
    dependencies=[Depends(validate_csrf_token)],
    description="Update the authenticated user's CSS theme preference.",
)
async def set_theme(
    request: Request,
    account: Annotated[Any, Depends(RequireLogin(AccountClaims.BASIC))],
    db: Database,
) -> dict[str, str]:
    """Update the authenticated user's theme preference.

    Theme changes are allowed even for defunct (read-only) accounts.

    :param request: The incoming request.
    :param account: The authenticated account.
    :param db: Active database session.
    :returns: A status dict with the applied theme.
    :rtype: dict[str, str]
    :raises HTTPException: If the theme is invalid.
    """
    try:
        body = await request.json()
        theme = body.get("theme", "")
    except Exception:
        theme = ""

    if theme not in VALID_THEMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid theme '{theme}'. Valid themes: {', '.join(sorted(VALID_THEMES))}",
        )

    with db:
        from sqlalchemy import select
        from models import DBAccount as Account

        act = db.scalars(select(Account).where(Account.id == account.id)).first()
        if act is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        act.theme = theme
        db.commit()

    return {"status": "ok", "theme": theme}
