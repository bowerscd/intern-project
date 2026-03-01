"""Tests for v0 legacy mealbot endpoints — permanently disabled (410 Gone)."""

from starlette.testclient import TestClient


class TestV0PermanentlyDisabled:
    """All v0 endpoints return 410 regardless of environment configuration."""

    def test_echo_returns_410(self, client: TestClient) -> None:
        """v0 echo returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.post("/api/echo", content=b"hello world")
        assert r.status_code == 410

    def test_get_data_returns_410(self, client: TestClient) -> None:
        """v0 get-data returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/get-data")
        assert r.status_code == 410

    def test_edit_meal_returns_410(self, client: TestClient) -> None:
        """v0 edit_meal returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.post("/api/edit_meal/alice/bobbi/3")
        assert r.status_code == 410

    def test_whoami_returns_410(self, client: TestClient) -> None:
        """v0 whoami returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/whoami/1")
        assert r.status_code == 410

    def test_410_detail_message(self, client: TestClient) -> None:
        """The 410 response includes a message directing users to v2.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/get-data")
        assert r.status_code == 410
        assert "/api/v2" in r.json()["detail"]
