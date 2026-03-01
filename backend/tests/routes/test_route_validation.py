"""
Tests for route validation issues:
- RequireLogin uses assert for runtime validation
- update_profile cannot unset phone (None = "don't update")
- Dead code account_id_map in v0 get_data
- EventCreate rejects past dates
"""

from datetime import datetime, UTC

import pytest


class TestCannotUnsetPhone:
    """
    ProfileUpdate uses Optional[str] = None where None
    means "don't update". This makes it impossible to unset a phone.
    """

    def test_json_null_treated_as_not_provided(self) -> None:
        """Sending {"phone": null} is the same as not sending phone."""
        from schemas.account import ProfileUpdate

        body_with_null = ProfileUpdate.model_validate({"phone": None})
        body_without = ProfileUpdate.model_validate({})

        # Both have phone == None — indistinguishable
        assert body_with_null.phone is None
        assert body_without.phone is None
        assert body_with_null.phone == body_without.phone, (
            "Cannot distinguish 'explicitly null' from 'not provided'"
        )

    def test_empty_string_rejected_by_pattern(self) -> None:
        """Sending {"phone": ""} is rejected by the \\d{10,15} pattern."""
        from pydantic import ValidationError
        from schemas.account import ProfileUpdate

        with pytest.raises(ValidationError):
            ProfileUpdate.model_validate({"phone": ""})


class TestEventCreateRejectsPastDates:
    """
    EventCreate schema requires 'when' to be in the future.
    """

    def test_past_date_rejected_by_schema(self) -> None:
        """EventCreate rejects scheduling events in the past."""
        from schemas.happyhour import EventCreate

        past = datetime(2020, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Event date must be in the future"):
            EventCreate(location_id=1, when=past, description=None)
