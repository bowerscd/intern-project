"""Tests for enum types: ExternalAuthProvider, PhoneProvider, AccountClaims."""

import pytest

from models.enums import ExternalAuthProvider, PhoneProvider, AccountClaims


class TestExternalAuthProvider:
    """Verify :class:`~models.enums.ExternalAuthProvider` validation and serialization."""

    def test_validate_valid_provider(self) -> None:
        """Verify a known provider value passes validation."""
        result = ExternalAuthProvider._validate("google")
        assert result == ExternalAuthProvider.google

    def test_validate_invalid_provider(self) -> None:
        """Verify an unknown value raises :class:`ValueError`."""
        with pytest.raises(ValueError):
            ExternalAuthProvider._validate("nonexistent")

    def test_serialize(self) -> None:
        """Verify enum serializes to its string value."""
        result = ExternalAuthProvider._serialize(ExternalAuthProvider.google)
        assert result == "google"

    def test_config_property(self) -> None:
        """Verify the ``config`` property returns a mapping."""
        assert ExternalAuthProvider.google.config == "https://accounts.google.com"

    def test_pydantic_core_schema(self) -> None:
        """Verify the Pydantic v2 core schema is generated."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(ExternalAuthProvider)

        result = adapter.validate_python("google")
        assert result == ExternalAuthProvider.google

        serialized = adapter.dump_python(ExternalAuthProvider.google, mode="json")
        assert serialized == "google"

    def test_pydantic_json_schema(self) -> None:
        """Verify the Pydantic v2 JSON schema is generated."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(ExternalAuthProvider)
        schema = adapter.json_schema()
        assert schema["type"] == "string"
        assert "enum" in schema


class TestPhoneProvider:
    """Verify :class:`~models.enums.PhoneProvider` gateway resolution."""

    def test_gateway_none(self) -> None:
        """Verify ``NONE`` provider has no gateway."""
        assert PhoneProvider.NONE.gateway is None

    def test_gateway_tmobile(self) -> None:
        """Verify T-Mobile provider resolves to its SMS gateway."""
        assert PhoneProvider.TMOBILE.gateway == "tmomail.net"


class TestAccountClaims:
    """Verify :class:`~models.enums.AccountClaims` flag algebra."""

    def test_any_has_all_claims(self) -> None:
        """Verify ``ANY`` includes every other claim flag."""
        all_claims = AccountClaims.ANY
        for c in AccountClaims:
            assert all_claims & c == c


class TestHappyHourTyrantDoesNotImplyHappyHour:
    """
    HAPPY_HOUR_TYRANT and HAPPY_HOUR are independent IntFlag bits.
    A user with only TYRANT would fail access checks requiring HAPPY_HOUR.
    """

    def test_tyrant_alone_fails_happy_hour_check(self) -> None:
        """AccountClaims.HAPPY_HOUR_TYRANT alone does not satisfy a HAPPY_HOUR check."""
        tyrant_only = AccountClaims.HAPPY_HOUR_TYRANT
        has_hh = tyrant_only & AccountClaims.HAPPY_HOUR == AccountClaims.HAPPY_HOUR
        assert not has_hh, "HAPPY_HOUR_TYRANT unexpectedly implies HAPPY_HOUR"

    def test_tyrant_and_happy_hour_are_independent_bits(self) -> None:
        """The two flags occupy different bits with no overlap."""
        assert (
            AccountClaims.HAPPY_HOUR_TYRANT.value & AccountClaims.HAPPY_HOUR.value == 0
        ), "HAPPY_HOUR_TYRANT bit overlaps with HAPPY_HOUR"
