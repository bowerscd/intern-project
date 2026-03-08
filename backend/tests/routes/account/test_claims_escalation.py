"""Tests for claims escalation guards: BASIC and ADMIN blocked from self-service."""

from starlette.testclient import TestClient


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
