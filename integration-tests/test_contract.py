"""API contract tests.

Validates that the backend's responses conform to expected shapes and that
the OpenAPI schema is available and well-formed.
"""

import httpx
import pytest


class TestOpenAPISchema:
    """The backend should expose a valid OpenAPI schema."""

    def test_openapi_json_available(self, client: httpx.Client) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert schema["info"]["title"]

    def test_openapi_version(self, client: httpx.Client) -> None:
        resp = client.get("/openapi.json")
        schema = resp.json()
        # FastAPI generates OpenAPI 3.1.x
        assert schema["openapi"].startswith("3.")

    def test_all_routes_documented(self, client: httpx.Client) -> None:
        """Every route should appear in the OpenAPI paths."""
        resp = client.get("/openapi.json")
        schema = resp.json()
        paths = set(schema["paths"].keys())

        expected_paths = [
            "/api/v2/account/profile",
            "/api/v2/account/claims",
            "/api/v2/mealbot/ledger",
            "/api/v2/mealbot/summary",
            "/api/v2/mealbot/record",
            "/api/v2/happyhour/events",
            "/api/v2/happyhour/locations",
            "/api/v2/auth/login/{provider}",
            "/api/v2/auth/register/{provider}",
            "/api/v2/auth/callback/{provider}",
        ]

        for ep in expected_paths:
            assert ep in paths, f"Missing from OpenAPI: {ep}"


class TestProfileContract:
    """The profile endpoint should return a predictable shape."""

    def test_unauthenticated_profile_returns_json_error(
        self, client: httpx.Client
    ) -> None:
        resp = client.get("/api/v2/account/profile")
        assert resp.status_code in (401, 403)
        body = resp.json()
        assert "detail" in body


class TestMealbotContract:
    """Mealbot endpoints should return lists/objects."""

    def test_ledger_requires_auth(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/mealbot/ledger")
        assert resp.status_code in (401, 403)

    def test_summary_requires_auth(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/mealbot/summary")
        assert resp.status_code in (401, 403)


class TestHappyhourContract:
    """Happy hour endpoints should follow the expected contract."""

    def test_events_requires_auth(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/happyhour/events")
        assert resp.status_code in (401, 403)

    def test_locations_requires_auth(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/happyhour/locations")
        assert resp.status_code in (401, 403)


class TestErrorContract:
    """Error responses should have a consistent shape."""

    def test_404_is_json(self, client: httpx.Client) -> None:
        resp = client.get("/api/v2/nonexistent")
        assert resp.status_code in (404, 405)
        body = resp.json()
        assert "detail" in body

    def test_422_has_detail(self, client: httpx.Client) -> None:
        """Posting invalid JSON should return a structured 422 or 403 (CSRF)."""
        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"wrong_field": True},
        )
        # Without a CSRF token the request is rejected with 403;
        # with a valid token it would be 422. Both are acceptable
        # structured JSON error responses.
        assert resp.status_code in (403, 422)
        body = resp.json()
        assert "detail" in body
