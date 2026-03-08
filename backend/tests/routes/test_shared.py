"""Tests for RequireLogin middleware: yield behavior and dependencies."""

from starlette.testclient import TestClient


class TestRequireLoginYield:
    """
    RequireLogin.__call__ uses yield (generator dependency).
    This tests that the generator pattern works correctly.
    """

    def test_authenticated_profile_endpoint_works(
        self, authenticated_client: TestClient
    ) -> None:
        """
        If the generator dependency causes DetachedInstanceError,
        this request would fail.

        :param authenticated_client: Pre-authenticated HTTP test client with all claims.
        :type authenticated_client: TestClient
        """
        resp = authenticated_client.get("/api/v2/account/profile")
        assert resp.status_code == 200, (
            f"Profile endpoint failed with {resp.status_code}: {resp.text}"
        )
