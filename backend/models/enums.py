"""Application-wide enumerations for providers, claims, and statuses."""

import os
from enum import Enum, IntFlag, auto
from typing import Any

from pydantic_core import CoreSchema
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue

from .internal import classproperty


class ExternalAuthProvider(Enum):
    """Supported external authentication providers.

    Each member stores an auto-generated integer value and an OIDC
    discovery URL used for provider configuration.

    The ``test`` provider's URL is configurable via the
    ``TEST_OIDC_ISSUER`` environment variable so it can point to a
    local mock OIDC server during development.
    """

    test = (auto(), os.environ.get("TEST_OIDC_ISSUER", "https://accounts.localhost"))
    google = (auto(), "https://accounts.google.com")

    @property
    def value(self) -> int:
        """Return the integer identifier for this provider.

        :returns: The provider's integer value.
        :rtype: int
        """
        return super(ExternalAuthProvider, self).value[0]

    @property
    def config(self) -> str:
        """Return the OIDC configuration URL for this provider.

        :returns: The provider's well-known configuration base URL.
        :rtype: str
        """
        return super(ExternalAuthProvider, self).value[1]

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Build a Pydantic core schema that validates strings into enum members.

        :param source_type: The annotated source type (must be
            :class:`ExternalAuthProvider`).
        :param handler: Pydantic schema generation handler.
        :returns: A Pydantic core schema for string-based validation.
        :rtype: CoreSchema
        """
        from pydantic_core import core_schema

        assert source_type is ExternalAuthProvider

        s = core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                cls._serialize, info_arg=False, return_schema=core_schema.str_schema()
            ),
        )

        def __return(
            _core_schema: CoreSchema, _handler: GetJsonSchemaHandler
        ) -> JsonSchemaValue:
            """Return a JSON-schema snippet listing the enum member names.

            :param _core_schema: The core schema (unused).
            :param _handler: The JSON-schema handler (unused).
            :returns: A JSON-schema ``{"type": "string", "enum": [...]}``.
            :rtype: JsonSchemaValue
            """
            return {"type": "string", "enum": [e.name for e in cls]}

        s.setdefault("metadata", {}).setdefault("pydantic_js_functions", []).append(
            __return
        )

        return s

    @staticmethod
    def _validate(value: str) -> "ExternalAuthProvider":
        """Validate a string and convert it to an :class:`ExternalAuthProvider` member.

        :param value: The provider name string.
        :returns: The matching enum member.
        :rtype: ExternalAuthProvider
        :raises ValueError: If *value* does not match a known provider.
        """
        providers = {i.name: i for i in ExternalAuthProvider}
        if value in providers:
            return providers[value]
        raise ValueError(f"invalid provider: {value!r}")

    @staticmethod
    def _serialize(value: "ExternalAuthProvider") -> str:
        """Serialize an :class:`ExternalAuthProvider` member to its name string.

        :param value: The enum member to serialize.
        :returns: The member's name.
        :rtype: str
        """
        return value.name


class PhoneProvider(Enum):
    """Supported phone carrier gateways for email-to-SMS delivery.

    Each member stores an auto-generated integer value and the
    carrier's MMS gateway domain (or ``None`` for the sentinel ``NONE``
    member).
    """

    NONE = (auto(), None)
    ALL_TELL = (auto(), "mms.alltelwireless.com")
    AT_T = (auto(), "mms.att.net")
    BOOST_WIRELESS = (auto(), "myboostmobile.com")
    CONSUMER_CELLULAR = (auto(), "mailmymobile.net")
    CRICKET_WIRELESS = (auto(), "mms.cricketwireless.net")
    FIRST_NET = (auto(), "sms.firstnet.com")
    GOOGLE_FI = (auto(), "msg.fi.google.com")
    METRO_PCS = (auto(), "mymetropcs.com")
    SPRINT = (auto(), "pm.sprint.com")
    TMOBILE = (auto(), "tmomail.net")
    US_CELLULAR = (auto(), "mms.uscc.net")
    VERIZON = (auto(), "vzwpix.com")
    VIRGIN_MOBILE = (auto(), "vmpix.com")
    XFINITY_MOBILE = (auto(), "mypixmessages.com")

    @property
    def value(self) -> int:
        """Return the integer identifier for this phone provider.

        :returns: The provider's integer value.
        :rtype: int
        """
        return super(PhoneProvider, self).value[0]

    @property
    def gateway(self) -> str | None:
        """Return the MMS gateway domain for this carrier.

        :returns: The carrier's MMS gateway, or ``None`` for the ``NONE``
            sentinel.
        :rtype: str | None
        """
        return super(PhoneProvider, self).value[1]


class TyrantAssignmentStatus(Enum):
    """Status values for a tyrant rotation assignment.

    Tracks whether a tyrant selection is still pending, has been
    fulfilled, was missed, or is scheduled for a future week.
    """

    SCHEDULED = "scheduled"
    PENDING = "pending"
    CHOSEN = "chosen"
    MISSED = "missed"


class AccountClaimStatus(Enum):
    """Status values for an account ownership claim request.

    A new OIDC user may claim ownership of a legacy/imported account.
    The claim must be approved by an admin before the accounts are linked.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class AccountClaims(IntFlag):
    """Bitmask flags representing account permission claims.

    Multiple claims can be combined using bitwise OR to grant a user
    several permissions simultaneously.
    """

    NONE = 0
    BASIC = auto()
    ADMIN = auto()
    MEALBOT = auto()
    COOKBOOK = auto()
    HAPPY_HOUR = auto()
    HAPPY_HOUR_TYRANT = auto()

    @classproperty
    def ANY(cls) -> "AccountClaims":
        """Return a bitmask with every defined claim enabled.

        :returns: A combined :class:`AccountClaims` value.
        :rtype: AccountClaims
        """
        v = AccountClaims.NONE
        for x in cls:
            v |= x
        return v
