"""Tests for AuthenticationHandler login flow."""

import pytest
from unittest.mock import AsyncMock, patch

from auth.config import AuthConfig
from auth.base import AuthenticationHandler
from tests import TEST_ENV_VAR_PREFIX


class ConcreteAuthHandler(AuthenticationHandler):
    """Concrete implementation for testing."""

    pass


MOCK_OIDC_CONFIG = {
    "authorization_endpoint": "https://accounts.example.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.example.com/token",
    "jwks_uri": "https://www.example.com/oauth2/v3/certs",
    "issuer": "https://accounts.example.com",
    "id_token_signing_alg_values_supported": ["RS256"],
}


@pytest.fixture
def auth_config() -> AuthConfig:
    """Build an :class:`~auth.config.AuthConfig` with the test env-var prefix."""
    return AuthConfig(
        site_root="https://accounts.example.com",
        var_prefix=TEST_ENV_VAR_PREFIX,
    )


@pytest.fixture
def handler(auth_config: AuthConfig) -> ConcreteAuthHandler:
    """Build a :class:`ConcreteAuthHandler` from the test auth config.

    :param auth_config: Test authentication configuration.
    :type auth_config: AuthConfig
    """
    return ConcreteAuthHandler(auth_config)


class TestLogin:
    """Verify :meth:`AuthenticationHandler.login` redirect behaviour."""

    @pytest.mark.asyncio
    async def test_login_returns_redirect(self, handler: ConcreteAuthHandler) -> None:
        """Verify ``login`` returns an HTTP 302 redirect.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        with patch.object(
            handler._config_mgr,
            "config",
            new_callable=AsyncMock,
            return_value=MOCK_OIDC_CONFIG,
        ):
            response = await handler.login("/home")
            # Should be a redirect response (302)
            assert response.status_code == 302

    @pytest.mark.asyncio
    async def test_login_sets_state_cookie(self, handler: ConcreteAuthHandler) -> None:
        """Verify ``login`` sets ``auth_state`` and ``auth_nonce`` cookies.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        with patch.object(
            handler._config_mgr,
            "config",
            new_callable=AsyncMock,
            return_value=MOCK_OIDC_CONFIG,
        ):
            response = await handler.login("/home")

            # Check cookies were set (state and nonce)
            cookie_headers = [h for h in response.raw_headers if h[0] == b"set-cookie"]
            cookie_names = [h[1].split(b"=")[0].decode() for h in cookie_headers]
            assert "auth_state" in cookie_names
            assert "auth_nonce" in cookie_names

    @pytest.mark.asyncio
    async def test_login_redirect_url_contains_params(
        self, handler: ConcreteAuthHandler
    ) -> None:
        """Verify the redirect URL includes required OIDC query parameters.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        with patch.object(
            handler._config_mgr,
            "config",
            new_callable=AsyncMock,
            return_value=MOCK_OIDC_CONFIG,
        ):
            response = await handler.login("/home", scopes={"openid", "email"})
            location = dict(response.raw_headers).get(b"location", b"").decode()
            assert "accounts.example.com" in location
            assert "response_type=code" in location
            assert "client_id=" in location


class TestAuthenticate:
    """Verify :meth:`AuthenticationHandler.authenticate` input validation."""

    @pytest.mark.asyncio
    async def test_authenticate_missing_nonce_raises(
        self, handler: ConcreteAuthHandler
    ) -> None:
        """Verify a missing ``auth_nonce`` cookie raises :class:`HTTPException`.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await handler.authenticate(
                cookies={},
                query_params={"state": "test", "code": "abc"},
            )

    @pytest.mark.asyncio
    async def test_authenticate_missing_state_raises(
        self, handler: ConcreteAuthHandler
    ) -> None:
        """Verify a missing ``auth_state`` cookie raises :class:`HTTPException`.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await handler.authenticate(
                cookies={"auth_nonce": "n1"},
                query_params={"state": "test", "code": "abc"},
            )

    @pytest.mark.asyncio
    async def test_authenticate_state_mismatch_raises(
        self, handler: ConcreteAuthHandler
    ) -> None:
        """Verify a state mismatch between cookie and query raises :class:`HTTPException`.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await handler.authenticate(
                cookies={"auth_nonce": "n1", "auth_state": "state1"},
                query_params={"state": "different", "code": "abc"},
            )

    @pytest.mark.asyncio
    async def test_authenticate_missing_code_raises(
        self, handler: ConcreteAuthHandler
    ) -> None:
        """Verify a missing ``code`` query parameter raises :class:`HTTPException`.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await handler.authenticate(
                cookies={"auth_nonce": "n1", "auth_state": "ok"},
                query_params={"state": "ok"},
            )


class TestAuthCookieSecureFlag:
    """Auth cookies respect DEV_MODE for the secure flag."""

    @pytest.mark.asyncio
    async def test_redirect_cookies_secure_in_production(
        self, handler: ConcreteAuthHandler
    ) -> None:
        """The OIDC redirect response sets Secure on auth cookies over HTTPS.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        """
        from starlette.responses import RedirectResponse

        with (
            patch("config.DEV_MODE", False),
            patch.object(
                handler._config_mgr,
                "config",
                new_callable=AsyncMock,
                return_value=MOCK_OIDC_CONFIG,
            ),
        ):
            response = await handler._redirect("https://example.com/start", {"openid"})

        assert isinstance(response, RedirectResponse)
        cookie_headers = [v for k, v in response.raw_headers if k == b"set-cookie"]
        assert len(cookie_headers) >= 2, "Expected state + nonce cookies"

        for raw in cookie_headers:
            header_str = raw.decode()
            assert "Secure" in header_str, (
                f"Cookie should be Secure in production: {header_str}"
            )
