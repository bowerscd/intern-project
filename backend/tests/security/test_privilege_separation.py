"""Reduced-privilege access tests.

Validates that claim-based authorization correctly restricts cross-module
access — e.g. a MEALBOT-only user cannot hit HAPPY_HOUR endpoints.
"""

import pytest
from starlette.testclient import TestClient


class TestMealbotOnlyCannotAccessHappyHour:
    """A user with only the MEALBOT claim should be rejected from HAPPY_HOUR routes."""

    def test_mealbot_user_cannot_list_events(self, mealbot_only_client: TestClient) -> None:
        """GET /api/v2/happyhour/events should return 403 for mealbot-only user."""
        resp = mealbot_only_client.get("/api/v2/happyhour/events")
        assert resp.status_code == 403

    def test_mealbot_user_cannot_list_locations(self, mealbot_only_client: TestClient) -> None:
        """GET /api/v2/happyhour/locations should return 403 for mealbot-only user."""
        resp = mealbot_only_client.get("/api/v2/happyhour/locations")
        assert resp.status_code == 403


class TestHappyHourOnlyCannotAccessMealbot:
    """A user with only the HAPPY_HOUR claim should be rejected from MEALBOT routes."""

    def test_hh_user_cannot_list_ledger(self, happyhour_only_client: TestClient) -> None:
        """GET /api/v2/mealbot/ledger should return 403 for happyhour-only user."""
        resp = happyhour_only_client.get("/api/v2/mealbot/ledger")
        assert resp.status_code == 403

    def test_hh_user_cannot_post_record(self, happyhour_only_client: TestClient) -> None:
        """POST /api/v2/mealbot/record should return 403 for happyhour-only user."""
        resp = happyhour_only_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "alice", "recipient": "bob", "credits": 1},
        )
        assert resp.status_code == 403
