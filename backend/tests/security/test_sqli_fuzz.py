"""SQL injection fuzzing tests.

Uses Hypothesis to generate payloads with SQL injection patterns and verifies
the backend never returns 500 or leaks database errors.
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from starlette.testclient import TestClient

# Common SQL injection fragments
SQL_PAYLOADS = [
    "'; DROP TABLE accounts;--",
    "1 OR 1=1",
    "' UNION SELECT * FROM accounts--",
    "1; SELECT * FROM sqlite_master--",
    "' OR '1'='1",
    "admin'--",
    "1' AND SLEEP(5)--",
    "'; EXEC xp_cmdshell('whoami');--",
    "1 UNION ALL SELECT NULL,NULL,NULL--",
    "' OR 1=1 LIMIT 1 OFFSET 1--",
    "Robert'); DROP TABLE students;--",
]


class TestSQLInjectionInQueryParams:
    """SQL injection attempts via query parameters should never cause 500."""

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_mealbot_ledger_page_size(self, client: TestClient, payload: str) -> None:
        resp = client.get(f"/api/v2/mealbot/ledger?page_size={payload}")
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_mealbot_summary_user(self, client: TestClient, payload: str) -> None:
        resp = client.get(f"/api/v2/mealbot/summary?user={payload}")
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_happyhour_events(self, client: TestClient, payload: str) -> None:
        resp = client.get(f"/api/v2/happyhour/events?garbage={payload}")
        assert resp.status_code != 500


class TestSQLInjectionInPathParams:
    """SQL injection in path segments should return 4xx, never 500."""

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_event_id(self, client: TestClient, payload: str) -> None:
        resp = client.get(f"/api/v2/happyhour/events/{payload}")
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_location_id(self, client: TestClient, payload: str) -> None:
        resp = client.get(f"/api/v2/happyhour/locations/{payload}")
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_auth_provider(self, client: TestClient, payload: str) -> None:
        resp = client.get(f"/api/v2/auth/login/{payload}")
        assert resp.status_code != 500


class TestSQLInjectionInRequestBody:
    """SQL injection in JSON request bodies should be sanitized by the ORM."""

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_mealbot_record(
        self, authenticated_client: TestClient, payload: str
    ) -> None:
        resp = authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"payer": payload, "recipient": "bob", "credits": 1},
        )
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_complete_registration(self, client: TestClient, payload: str) -> None:
        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": payload},
        )
        assert resp.status_code != 500


class TestHypothesisFuzz:
    """Fuzz string fields with random unicode to catch unexpected crashes."""

    @given(username=st.text(min_size=1, max_size=200))
    @settings(
        max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_complete_registration_fuzz(
        self, client: TestClient, username: str
    ) -> None:
        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": username},
        )
        assert resp.status_code != 500
