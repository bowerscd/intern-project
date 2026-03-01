"""Tests for RequireLogin middleware: yield behavior, status codes, dependencies."""

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


class TestStatusCodeSemantics:
    """
    RequireLogin returns proper HTTP status codes:
    - Missing session -> 401 (from APIKeyCookie)
    - Has session but wrong claims -> 403 (Forbidden)
    """

    def test_unauthenticated_returns_401_from_apikeycookie(
        self, client: TestClient
    ) -> None:
        """A request with no session cookie gets 401 from APIKeyCookie.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        resp = client.get("/api/v2/account/profile")
        assert resp.status_code == 401, (
            f"Expected 401 from APIKeyCookie, got {resp.status_code}"
        )
