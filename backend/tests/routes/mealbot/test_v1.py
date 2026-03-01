"""Tests for v1 legacy mealbot endpoints — permanently disabled (410 Gone)."""

from starlette.testclient import TestClient


class TestV1PermanentlyDisabled:
    """All v1 endpoints return 410 regardless of environment configuration."""

    def test_create_user_returns_410(self, client: TestClient) -> None:
        """v1 User creation returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.post("/api/v1/User", json={"user": "alice", "operation": "CREATE"})
        assert r.status_code == 410

    def test_summary_returns_410(self, client: TestClient) -> None:
        """v1 Summary returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v1/Summary")
        assert r.status_code == 410

    def test_record_get_returns_410(self, client: TestClient) -> None:
        """v1 Record GET returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v1/Record")
        assert r.status_code == 410

    def test_record_post_returns_410(self, client: TestClient) -> None:
        """v1 Record POST returns 410 Gone.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.post(
            "/api/v1/Record",
            json={"payer": "alice", "recipient": "bobbi", "credits": 3},
        )
        assert r.status_code == 410

    def test_410_detail_message(self, client: TestClient) -> None:
        """The 410 response includes a message directing users to v2.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        r = client.get("/api/v1/Summary")
        assert r.status_code == 410
        assert "/api/v2" in r.json()["detail"]
