"""Concurrency-safety tests.

Note: The backend uses SQLite in-memory for tests, which is not thread-safe.
True concurrent request testing belongs in the integration test suite
(vibe-integrated) where a real server with connection pooling is used.

These tests instead validate sequential request independence — ensuring
that one request's state doesn't leak into the next.
"""

from starlette.testclient import TestClient


class TestSequentialRequestIsolation:
    """Sequential requests should not leak state between each other."""

    def test_profile_idempotent(self, authenticated_client: TestClient) -> None:
        """Multiple sequential GET /profile calls return the same result."""
        resp1 = authenticated_client.get("/api/v2/account/profile")
        resp2 = authenticated_client.get("/api/v2/account/profile")
        assert resp1.status_code == resp2.status_code == 200
        assert resp1.json() == resp2.json()

    def test_events_list_consistent(self, authenticated_client: TestClient) -> None:
        """Multiple sequential event list calls return consistent results."""
        resp1 = authenticated_client.get("/api/v2/happyhour/events")
        resp2 = authenticated_client.get("/api/v2/happyhour/events")
        assert resp1.status_code == resp2.status_code == 200
        assert resp1.json() == resp2.json()

    def test_different_endpoints_independent(
        self, authenticated_client: TestClient
    ) -> None:
        """Calling different endpoints doesn't interfere with each other."""
        p = authenticated_client.get("/api/v2/account/profile")
        e = authenticated_client.get("/api/v2/happyhour/events")
        loc = authenticated_client.get("/api/v2/happyhour/locations")
        assert p.status_code == 200
        assert e.status_code == 200
        assert loc.status_code == 200

    def test_error_does_not_poison_next_request(
        self, authenticated_client: TestClient
    ) -> None:
        """A failed request should not affect the next successful one."""
        # Trigger a 422 with bad data
        authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"bad": "schema"},
        )
        # Follow up with a valid request
        resp = authenticated_client.get("/api/v2/account/profile")
        assert resp.status_code == 200
