"""Input fuzzing tests — malformed JSON, oversized payloads, unexpected types.

Validates that the backend handles garbage input gracefully without 500s.
"""

import pytest
from hypothesis import given, strategies as st, settings
from starlette.testclient import TestClient


class TestMalformedJSON:
    """Requests with invalid JSON bodies should return 422, not 500."""

    ENDPOINTS = [
        ("POST", "/api/v2/auth/complete-registration"),
        ("POST", "/api/v2/mealbot/record"),
        ("PATCH", "/api/v2/account/profile"),
        ("PATCH", "/api/v2/account/claims"),
        ("POST", "/api/v2/happyhour/events"),
        ("POST", "/api/v2/happyhour/locations"),
    ]

    @pytest.mark.parametrize("method, path", ENDPOINTS)
    def test_empty_body(self, authenticated_client: TestClient, method: str, path: str) -> None:
        resp = authenticated_client.request(method, path, content=b"")
        assert resp.status_code in (400, 422)

    @pytest.mark.parametrize("method, path", ENDPOINTS)
    def test_garbage_body(self, authenticated_client: TestClient, method: str, path: str) -> None:
        resp = authenticated_client.request(
            method, path,
            content=b"not json at all {{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.parametrize("method, path", ENDPOINTS)
    def test_null_body(self, authenticated_client: TestClient, method: str, path: str) -> None:
        resp = authenticated_client.request(
            method, path,
            content=b"null",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code != 500

    @pytest.mark.parametrize("method, path", ENDPOINTS)
    def test_array_instead_of_object(self, authenticated_client: TestClient, method: str, path: str) -> None:
        resp = authenticated_client.request(
            method, path,
            content=b"[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code != 500


class TestOversizedPayloads:
    """Very large inputs should be handled cleanly."""

    def test_oversized_username(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "A" * 10000},
        )
        assert resp.status_code != 500

    def test_oversized_json_body(self, authenticated_client: TestClient) -> None:
        huge = {"key_" + str(i): "value" * 100 for i in range(1000)}
        resp = authenticated_client.post(
            "/api/v2/mealbot/record",
            json=huge,
        )
        assert resp.status_code != 500


class TestUnexpectedTypes:
    """Fields with wrong types should return 422, not 500."""

    def test_credits_as_string(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "alice", "recipient": "bob", "credits": "not_a_number"},
        )
        assert resp.status_code in (400, 422)

    def test_location_id_as_string(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.post(
            "/api/v2/happyhour/events",
            json={"location_id": "abc", "when": "2025-01-01T12:00:00"},
        )
        assert resp.status_code in (400, 422)

    def test_claims_add_as_number(self, authenticated_client: TestClient) -> None:
        resp = authenticated_client.patch(
            "/api/v2/account/claims",
            json={"add": 42},
        )
        assert resp.status_code in (400, 422)


class TestNullByte:
    """Null bytes in input should not cause crashes."""

    def test_null_byte_in_username(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "user\x00injected"},
        )
        assert resp.status_code != 500

    def test_null_byte_in_query_param(self, client: TestClient) -> None:
        import httpx

        # httpx rejects null bytes in URLs at the client level — this is
        # valid protection: the request never reaches the server.
        with pytest.raises(httpx.InvalidURL):
            client.get("/api/v2/mealbot/summary?user=alice\x00admin")
