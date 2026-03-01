"""Tests for v2 account endpoints."""

from models import AccountClaims
from starlette.testclient import TestClient


class TestAccountUnauthenticated:
    """Verify account endpoints reject unauthenticated requests."""

    def test_profile_requires_auth(self, client: TestClient) -> None:
        """Verify ``GET /profile`` returns 403 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v2/account/profile")
        assert r.status_code == 401

    def test_update_profile_requires_auth(self, client: TestClient) -> None:
        """Verify ``PATCH /profile`` returns 403 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.patch("/api/v2/account/profile", json={"phone": "5551234"})
        assert r.status_code == 401

    def test_update_claims_requires_auth(self, client: TestClient) -> None:
        """Verify ``PATCH /claims`` returns 403 without auth.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.patch("/api/v2/account/claims", json={"add": ["MEALBOT"]})
        assert r.status_code == 401


class TestAccountAuthenticated:
    """Verify account endpoints with an authenticated client."""

    def test_get_profile(self, authenticated_client: TestClient) -> None:
        """Verify the authenticated user's profile is returned.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.get("/api/v2/account/profile")
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "test"
        assert "claims" in data

    def test_update_phone(self, authenticated_client: TestClient) -> None:
        """Verify phone number and provider can be updated.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/profile",
            json={
                "phone": "5551234567",
                "phone_provider": "VERIZON",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["phone"] == "5551234567"

    def test_update_invalid_provider(self, authenticated_client: TestClient) -> None:
        """Verify an invalid phone provider is rejected.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/profile",
            json={
                "phone_provider": "INVALID_CARRIER",
            },
        )
        assert r.status_code == 400


class TestClaimsSelfService:
    """Test PATCH /api/v2/account/claims."""

    def test_add_valid_claim(self, authenticated_client: TestClient) -> None:
        """Should be able to add a non-admin claim.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": ["MEALBOT"],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["claims"] & AccountClaims.MEALBOT == AccountClaims.MEALBOT

    def test_add_multiple_claims(self, authenticated_client: TestClient) -> None:
        """Should be able to add multiple non-admin claims at once.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": ["MEALBOT", "HAPPY_HOUR", "COOKBOOK"],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["claims"] & AccountClaims.MEALBOT == AccountClaims.MEALBOT
        assert data["claims"] & AccountClaims.HAPPY_HOUR == AccountClaims.HAPPY_HOUR
        assert data["claims"] & AccountClaims.COOKBOOK == AccountClaims.COOKBOOK

    def test_remove_claim(self, authenticated_client: TestClient) -> None:
        """Should be able to remove a claim.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        # The authenticated_client has ALL claims by default
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "remove": ["COOKBOOK"],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["claims"] & AccountClaims.COOKBOOK == 0

    def test_add_and_remove_simultaneously(
        self, authenticated_client: TestClient
    ) -> None:
        """Should handle add and remove in the same request.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": ["HAPPY_HOUR"],
                "remove": ["COOKBOOK"],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["claims"] & AccountClaims.HAPPY_HOUR == AccountClaims.HAPPY_HOUR
        assert data["claims"] & AccountClaims.COOKBOOK == 0

    def test_add_admin_claim_rejected(self, authenticated_client: TestClient) -> None:
        """Adding ADMIN claim should be rejected with 400.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": ["ADMIN"],
            },
        )
        assert r.status_code == 400
        assert "admin-level" in r.json()["detail"].lower()

    def test_remove_admin_claim_rejected(
        self, authenticated_client: TestClient
    ) -> None:
        """Removing ADMIN claim should also be rejected with 400.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "remove": ["ADMIN"],
            },
        )
        assert r.status_code == 400

    def test_invalid_claim_name_rejected(
        self, authenticated_client: TestClient
    ) -> None:
        """Invalid claim names should be rejected with 400.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": ["DOES_NOT_EXIST"],
            },
        )
        assert r.status_code == 400
        assert "invalid claim" in r.json()["detail"].lower()

    def test_add_HAPPY_HOUR_TYRANT_allowed(
        self, authenticated_client: TestClient
    ) -> None:
        """HAPPY_HOUR_TYRANT is not blocked — only ADMIN is.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        r = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": ["HAPPY_HOUR_TYRANT"],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert (
            data["claims"] & AccountClaims.HAPPY_HOUR_TYRANT
            == AccountClaims.HAPPY_HOUR_TYRANT
        )

    def test_empty_request_is_noop(self, authenticated_client: TestClient) -> None:
        """Empty add/remove lists should succeed without changing claims.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        # Get current claims
        r1 = authenticated_client.get("/api/v2/account/profile")
        original_claims = r1.json()["claims"]

        r2 = authenticated_client.patch(
            "/api/v2/account/claims",
            json={
                "add": [],
                "remove": [],
            },
        )
        assert r2.status_code == 200
        assert r2.json()["claims"] == original_claims
