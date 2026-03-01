"""Open redirect tests for the OIDC login/register endpoints.

Validates that the ``redirect`` query parameter only accepts relative paths
or origins explicitly listed in AUTH_REDIRECT_ORIGINS.

The OIDC provider is not available in unit tests, so we test the
``_validate_redirect`` function directly where the actual security gate lives,
and verify the HTTP-level 400 rejection for clearly malicious redirects.
"""

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from routes.auth.login import _validate_redirect


# Payloads whose urlparse() output has a scheme or netloc — _validate_redirect
# can reject these synchronously before any OIDC fetch happens.
EVIL_REDIRECTS_REJECTED_SYNC = [
    "https://evil.example.com/steal-creds",
    "//evil.example.com",
    "http://evil.example.com",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "https://evil.example.com@legitimate.com",
    "https://evil.example.com%00@legitimate.com",
    "https://evil.example.com/path?q=http://trusted.example.com",
]

# Payloads that contain backslashes — now also rejected by _validate_redirect
# to prevent exploitation of browser backslash→slash normalisation.
BACKSLASH_REDIRECTS = [
    "\\\\evil.example.com",
]


class TestValidateRedirectFunction:
    """Direct unit tests for the _validate_redirect helper."""

    @pytest.mark.parametrize("redirect", EVIL_REDIRECTS_REJECTED_SYNC)
    def test_evil_redirect_raises(self, redirect: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validate_redirect(redirect)
        assert exc_info.value.status_code == 400

    @pytest.mark.parametrize("redirect", ["/account", "/mealbot", "/happyhour/manage"])
    def test_relative_redirect_passes(self, redirect: str) -> None:
        result = _validate_redirect(redirect)
        assert result == redirect

    def test_allowlisted_origin_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        login_module = sys.modules["routes.auth.login"]
        monkeypatch.setattr(
            login_module, "AUTH_REDIRECT_ORIGINS", ["https://frontend.example.com"]
        )
        result = _validate_redirect("https://frontend.example.com/account")
        assert result == "https://frontend.example.com/account"

    def test_unlisted_origin_rejected(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validate_redirect("https://unknown.example.com/foo")
        assert exc_info.value.status_code == 400

    @pytest.mark.parametrize("redirect", BACKSLASH_REDIRECTS)
    def test_backslash_redirect_rejected(self, redirect: str) -> None:
        """Backslash URLs are rejected to prevent browser normalisation exploits."""
        with pytest.raises(HTTPException) as exc_info:
            _validate_redirect(redirect)
        assert exc_info.value.status_code == 400


class TestOpenRedirectHTTP:
    """HTTP-level tests: evil redirects that are caught before the OIDC fetch."""

    @pytest.mark.parametrize("redirect", EVIL_REDIRECTS_REJECTED_SYNC)
    def test_evil_redirect_rejected_login(
        self, client: TestClient, redirect: str
    ) -> None:
        resp = client.get(
            f"/api/v2/auth/login/test?redirect={redirect}",
            follow_redirects=False,
        )
        assert resp.status_code == 400, f"Login accepted dangerous redirect: {redirect}"

    @pytest.mark.parametrize("redirect", EVIL_REDIRECTS_REJECTED_SYNC)
    def test_evil_redirect_rejected_register(
        self, client: TestClient, redirect: str
    ) -> None:
        resp = client.get(
            f"/api/v2/auth/register/test?redirect={redirect}",
            follow_redirects=False,
        )
        assert resp.status_code == 400, (
            f"Register accepted dangerous redirect: {redirect}"
        )
