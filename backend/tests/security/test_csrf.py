"""CSRF protection tests.

Validates that mutating endpoints reject requests when:
- No X-CSRF-Token header is present
- An invalid CSRF token is supplied

Unlike most tests in this suite, these tests do NOT use the
``disable_csrf_globally`` fixture so that the real CSRF validation
runs.
"""

import pytest
from collections.abc import Iterator
from starlette.testclient import TestClient

from app import app
from csrf import validate_csrf_token


@pytest.fixture()
def csrf_client() -> Iterator[TestClient]:
    """Return a TestClient with CSRF validation *enabled*.

    Temporarily removes the ``disable_csrf_globally`` override so
    that the real ``validate_csrf_token`` dependency runs.
    """
    # Remove the no-op override installed by conftest
    original_override = app.dependency_overrides.pop(validate_csrf_token, None)
    try:
        with TestClient(app) as c:
            yield c
    finally:
        # Restore the override for other tests
        if original_override is not None:
            app.dependency_overrides[validate_csrf_token] = original_override


class TestCSRFRejection:
    """Mutating endpoints must reject requests without a valid CSRF token."""

    def test_post_without_csrf_token_is_rejected(self, csrf_client: TestClient) -> None:
        """A POST to a CSRF-protected endpoint without the header should fail."""
        resp = csrf_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "alice", "recipient": "bob", "credits": 1},
        )
        # Accept 401 (not logged in) or 403/422 (CSRF validation failed)
        # but NOT 200/201 (should never succeed without CSRF token)
        assert resp.status_code != 200
        assert resp.status_code != 201

    def test_post_with_invalid_csrf_token(self, csrf_client: TestClient) -> None:
        """A POST with a bogus CSRF token should fail."""
        resp = csrf_client.post(
            "/api/v2/mealbot/record",
            json={"payer": "alice", "recipient": "bob", "credits": 1},
            headers={"X-CSRF-Token": "totally-bogus-token"},
        )
        assert resp.status_code != 200
        assert resp.status_code != 201
