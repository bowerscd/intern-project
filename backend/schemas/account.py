"""
Pydantic schemas for Account API request/response models.
"""

import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

USERNAME_PATTERN = re.compile(r"^\w{1,36}$")


class ProfileResponse(BaseModel):
    """Response schema representing a user's profile.

    :cvar id: Account primary key.
    :cvar username: Unique username.
    :cvar oidc_email: Email from the OIDC provider (session-sourced, never null if logged in via OIDC).
    :cvar email: Stored notification email, or ``None`` when opt-out.
    :cvar phone: Phone number, or ``None``.
    :cvar phone_provider: Name of the phone carrier.
    :cvar claims: Bitmask of account claims.
    """

    id: int
    username: str
    oidc_email: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    phone_provider: str
    claims: int

    @staticmethod
    def from_account(act: Any, oidc_email: Optional[str] = None) -> "ProfileResponse":
        """Build a :class:`ProfileResponse` from a database account entity.

        :param act: An :class:`Account` ORM instance.
        :param oidc_email: The OIDC provider email from the session, if available.
        :returns: A populated response model.
        :rtype: ProfileResponse
        """
        return ProfileResponse(
            id=act.id,
            username=act.username,
            oidc_email=oidc_email,
            email=act.email,
            phone=act.phone,
            phone_provider=act.phone_provider.name
            if hasattr(act.phone_provider, "name")
            else str(act.phone_provider),
            claims=int(act.claims) if hasattr(act.claims, "__int__") else act.claims,
        )


class ProfileUpdate(BaseModel):
    """Request schema for updating a user's profile.

    Used to set the username, email address, phone number, and carrier.

    :cvar username: New username, or ``None`` to leave unchanged.
    :cvar email: New email address, or ``None`` to leave unchanged.
    :cvar phone: New phone number, or ``None`` to leave unchanged.
    :cvar phone_provider: New carrier name, or ``None`` to leave unchanged.
    """

    username: Optional[str] = Field(
        None,
        description="Unique username (1-36 word characters)",
        min_length=1,
        max_length=36,
    )
    email: Optional[str] = Field(None, description="Email address for notifications")
    phone: Optional[str] = Field(
        None, description="Phone number for SMS notifications", pattern=r"^\d{10,15}$"
    )
    phone_provider: Optional[str] = Field(
        None, description="Phone carrier name (e.g. VERIZON, AT_T)"
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: Optional[str]) -> Optional[str]:
        """Validate that the username matches the allowed pattern."""
        if v is not None and not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must be 1-36 characters using only letters, numbers, and underscores."
            )
        return v


class ClaimsUpdate(BaseModel):
    """Request schema for self-service claims management.

    Lists claim names to add and/or remove from the authenticated
    user's account.

    :cvar add: Claim names to add.
    :cvar remove: Claim names to remove.
    """

    add: list[str] = Field(
        default_factory=list,
        description="Claim names to add (e.g. MEALBOT, HAPPY_HOUR)",
    )
    remove: list[str] = Field(default_factory=list, description="Claim names to remove")


class CompleteRegistrationRequest(BaseModel):
    """Request schema for completing a new account registration.

    The user picks a username after OIDC authentication.

    :cvar username: Desired username (1-36 word characters).
    """

    username: str = Field(
        ...,
        description="Desired username (alphanumeric + underscores, 1-36 chars)",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Enforce the ``\\w{1,36}`` username pattern.

        :param v: Candidate username.
        :returns: The validated username.
        :raises ValueError: If the username does not match.
        """
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must match \\w{1,36} (alphanumeric + underscores, 1-36 chars)"
            )
        return v


class ClaimAccountRequest(BaseModel):
    """Request schema for claiming ownership of an existing legacy account.

    :cvar username: The username of the legacy account to claim.
    """

    username: str = Field(
        ...,
        description="Username of the existing account to claim",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Enforce the ``\\w{1,36}`` username pattern.

        :param v: Candidate username.
        :returns: The validated username.
        :raises ValueError: If the username does not match.
        """
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username must match \\w{1,36} (alphanumeric + underscores, 1-36 chars)"
            )
        return v


class ClaimRequestResponse(BaseModel):
    """Response schema for an account claim request (admin view).

    :cvar id: Claim request primary key.
    :cvar requester_provider: OIDC provider of the claimant.
    :cvar requester_external_id: OIDC 'sub' of the claimant.
    :cvar requester_name: Display name from the OIDC identity.
    :cvar requester_email: Email from the OIDC identity, or ``None``.
    :cvar target_account_id: ID of the legacy account being claimed.
    :cvar target_username: Username of the legacy account.
    :cvar status: Current claim status (pending/approved/denied).
    :cvar created_at: When the claim was submitted.
    :cvar resolved_at: When the claim was approved/denied, or ``None``.
    """

    id: int
    requester_provider: str
    requester_external_id: str
    requester_name: str
    requester_email: Optional[str]
    target_account_id: int
    target_username: str
    status: str
    created_at: Optional[str]
    resolved_at: Optional[str]


class ClaimReviewRequest(BaseModel):
    """Request schema for an admin reviewing a claim request.

    :cvar decision: Either ``"approve"`` or ``"deny"``.
    """

    decision: str = Field(
        ...,
        description="Either 'approve' or 'deny'",
    )

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        """Ensure decision is one of the allowed values.

        :param v: Candidate decision.
        :returns: The validated decision.
        :raises ValueError: If the decision is not allowed.
        """
        if v.lower() not in ("approve", "deny"):
            raise ValueError("Decision must be 'approve' or 'deny'")
        return v.lower()
