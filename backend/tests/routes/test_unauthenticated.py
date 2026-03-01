"""Tests for v0/v1 legacy endpoint permanent disable behavior."""
import pytest
from starlette.testclient import TestClient


class TestLegacyEndpointsPermanentlyDisabled:
    """Legacy v0/v1 endpoints always return 410 Gone."""

    def test_enable_legacy_env_var_has_no_effect(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting ENABLE_LEGACY_MEALBOT=1 no longer re-enables legacy endpoints.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param monkeypatch: Pytest monkey-patching helper.
        :type monkeypatch: pytest.MonkeyPatch
        """
        monkeypatch.setenv("ENABLE_LEGACY_MEALBOT", "1")
        resp = client.get("/api/get-data")
        assert resp.status_code == 410, (
            "ENABLE_LEGACY_MEALBOT should no longer bypass the 410"
        )
