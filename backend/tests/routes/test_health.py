"""Tests for the /healthz backend endpoint."""

import pytest
from starlette.testclient import TestClient


class TestHealthEndpoint:
    """Verify the health check endpoint is accessible and functional."""

    def test_healthz_returns_200(self, client: TestClient) -> None:
        """The health endpoint should return 200 when DB is reachable."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"

    def test_healthz_no_auth_required(self, client: TestClient) -> None:
        """The health endpoint must be accessible without authentication."""
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_content_type(self, client: TestClient) -> None:
        """The health endpoint should return application/json."""
        resp = client.get("/healthz")
        assert "application/json" in resp.headers.get("content-type", "")
