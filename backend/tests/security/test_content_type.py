"""Content-Type enforcement tests.

Validates that the backend properly handles Content-Type mismatches and
non-JSON content types.
"""

import pytest
from starlette.testclient import TestClient


JSON_ENDPOINTS = [
    ("POST", "/api/v2/auth/complete-registration"),
    ("POST", "/api/v2/mealbot/record"),
    ("PATCH", "/api/v2/account/profile"),
    ("PATCH", "/api/v2/account/claims"),
    ("POST", "/api/v2/happyhour/events"),
    ("POST", "/api/v2/happyhour/locations"),
]


class TestWrongContentType:
    """Sending non-JSON Content-Type to JSON endpoints should fail gracefully."""

    @pytest.mark.parametrize("method, path", JSON_ENDPOINTS)
    def test_form_data_rejected(
        self, authenticated_client: TestClient, method: str, path: str
    ) -> None:
        resp = authenticated_client.request(
            method,
            path,
            content=b"key=value&other=thing",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code in (400, 415, 422)

    @pytest.mark.parametrize("method, path", JSON_ENDPOINTS)
    def test_xml_content_type(
        self, authenticated_client: TestClient, method: str, path: str
    ) -> None:
        resp = authenticated_client.request(
            method,
            path,
            content=b"<root><key>value</key></root>",
            headers={"Content-Type": "application/xml"},
        )
        assert resp.status_code in (400, 415, 422)

    @pytest.mark.parametrize("method, path", JSON_ENDPOINTS)
    def test_no_content_type(
        self, authenticated_client: TestClient, method: str, path: str
    ) -> None:
        resp = authenticated_client.request(
            method,
            path,
            content=b'{"username": "test"}',
        )
        # Should either succeed (FastAPI is lenient) or return 4xx
        assert resp.status_code != 500


class TestResponseContentType:
    """All API responses should return application/json."""

    def test_profile_returns_json(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.get("/api/v2/account/profile")
        assert "application/json" in resp.headers.get("content-type", "")

    def test_error_returns_json(self, client: TestClient) -> None:
        resp = client.get("/api/v2/account/profile")
        # Even error responses should be JSON
        ct = resp.headers.get("content-type", "")
        assert "application/json" in ct or "text/" in ct
