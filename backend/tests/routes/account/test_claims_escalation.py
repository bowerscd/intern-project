"""Tests for claims self-escalation: only ADMIN is blocked from self-assignment."""

from starlette.testclient import TestClient


class TestClaimsEscalation:
    """
    Only ADMIN is blocked from self-assignment. A BASIC user can
    self-assign HAPPY_HOUR_TYRANT, MEALBOT, etc.
    """

    def test_can_self_assign_happy_hour_tyrant(
        self, authenticated_client: TestClient
    ) -> None:
        """An authenticated user can give themselves HAPPY_HOUR_TYRANT.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        resp = authenticated_client.patch(
            "/api/v2/account/claims",
            json={"add": ["HAPPY_HOUR_TYRANT"], "remove": []},
        )
        assert resp.status_code == 200, (
            f"Self-escalation to HAPPY_HOUR_TYRANT succeeded: {resp.status_code}"
        )

    def test_cannot_self_assign_admin(self, authenticated_client: TestClient) -> None:
        """ADMIN is properly blocked.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        resp = authenticated_client.patch(
            "/api/v2/account/claims",
            json={"add": ["ADMIN"], "remove": []},
        )
        assert resp.status_code == 400, (
            f"ADMIN self-assignment correctly blocked: {resp.status_code}"
        )


class TestBasicClaimProtected:
    """BASIC is now blocked from self-removal to prevent self-lockout."""

    def test_basic_in_blocked_claims(self) -> None:
        """Verify ``BASIC`` is present in the blocked-claims list."""
        from routes.account.claims import BLOCKED_CLAIMS

        assert "BASIC" in BLOCKED_CLAIMS, (
            "FIXED: BASIC is now in BLOCKED_CLAIMS, preventing self-lockout"
        )

    def test_self_remove_basic_rejected(self, authenticated_client: TestClient) -> None:
        """Removing BASIC claim should be blocked.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        resp = authenticated_client.patch(
            "/api/v2/account/claims",
            json={"add": [], "remove": ["BASIC"]},
        )
        assert resp.status_code == 400, "FIXED: Removing BASIC is now blocked"
