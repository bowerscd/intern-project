"""Tests for full AuthenticationHandler flow with local OIDC server."""
import json
import pytest
from datetime import datetime, UTC, timedelta
from hashlib import sha256
from base64 import urlsafe_b64encode
from urllib.parse import urlencode, quote

from jwt import encode as jwt_encode
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from pytest_httpserver import HTTPServer

from auth.config import AuthConfig
from auth.base import AuthenticationHandler

from tests import TEST_ENV_VAR_PREFIX
from collections.abc import Generator
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


class ConcreteAuthHandler(AuthenticationHandler):
    """Concrete implementation for testing."""
    pass


def _make_rsa_keypair() -> RSAPrivateKey:
    """Generate an RSA key pair for signing JWTs."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key


def _key_to_jwk(private_key: RSAPrivateKey) -> dict:
    """Convert RSA public key to JWK format.

    :param private_key: RSA private key for JWT signing.
    :type private_key: rsa.RSAPrivateKey
    :returns: JWK dictionary.
    :rtype: dict
    """
    from jwt.algorithms import RSAAlgorithm

    public_key = private_key.public_key()
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = "test-key-1"
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"
    return jwk_dict


def _sign_jwt(private_key: RSAPrivateKey, payload: dict, kid: str = "test-key-1") -> str:
    """Sign a JWT with the given private key.

    :param private_key: RSA private key for JWT signing.
    :type private_key: rsa.RSAPrivateKey
    :param payload: JWT claims payload.
    :type payload: dict
    :param kid: JWT key ID header value.
    :type kid: str
    :returns: Encoded JWT string.
    :rtype: str
    """
    return jwt_encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _compute_at_hash(access_token: str) -> str:
    """Compute at_hash from access_token per OIDC spec.

    :param access_token: Raw access token string.
    :type access_token: str
    :returns: Base64url-encoded ``at_hash`` claim value.
    :rtype: str
    """
    digest = sha256(access_token.encode()).digest()
    half = digest[: len(digest) // 2]
    return urlsafe_b64encode(half).rstrip(b"=").decode()


@pytest.fixture
def rsa_keypair() -> RSAPrivateKey:
    """Generate a fresh RSA key pair for JWT signing."""
    return _make_rsa_keypair()


@pytest.fixture
def local_httpserver() -> Generator[HTTPServer, None, None]:
    """Create a pytest-httpserver instance (distinct from pytest-localserver's httpserver)."""
    server = HTTPServer(host="127.0.0.1")
    server.start()
    yield server
    server.clear()
    if server.is_running():
        server.stop()


@pytest.fixture
def oidc_server(local_httpserver: HTTPServer, rsa_keypair: RSAPrivateKey) -> tuple[HTTPServer, dict[str, object]]:
    """Set up a local OIDC server with discovery, JWKS, and token endpoints.

    :param local_httpserver: Local HTTP test server.
    :type local_httpserver: HTTPServer
    :param rsa_keypair: Generated RSA private/public key pair.
    :type rsa_keypair: tuple
    """
    base_url = local_httpserver.url_for("")

    # Discovery document
    discovery = {
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "jwks_uri": f"{base_url}/jwks",
        "issuer": base_url.rstrip("/"),
        "id_token_signing_alg_values_supported": ["RS256"],
    }

    local_httpserver.expect_request(
        "/.well-known/openid-configuration"
    ).respond_with_json(discovery)

    # JWKS endpoint
    jwk = _key_to_jwk(rsa_keypair)
    local_httpserver.expect_request("/jwks").respond_with_json({"keys": [jwk]})

    return local_httpserver, discovery


@pytest.fixture
def auth_config(oidc_server: tuple[HTTPServer, dict[str, object]]) -> AuthConfig:
    """Build an :class:`~auth.config.AuthConfig` backed by the local OIDC server.

    :param oidc_server: Local OIDC server and discovery document.
    :type oidc_server: tuple
    """
    httpserver, discovery = oidc_server
    base_url = httpserver.url_for("").rstrip("/")
    return AuthConfig(
        site_root=base_url,
        var_prefix=TEST_ENV_VAR_PREFIX,
        update_interval=timedelta(seconds=0),  # Don't cache for tests
    )


@pytest.fixture
def handler(auth_config: AuthConfig) -> ConcreteAuthHandler:
    """Build a :class:`ConcreteAuthHandler` from the local auth config.

    :param auth_config: Test authentication configuration.
    :type auth_config: AuthConfig
    """
    return ConcreteAuthHandler(auth_config)


class TestVerifyTokenExchange:
    """Tests for the full token verification flow."""

    @pytest.mark.asyncio
    async def test_verify_valid_id_token(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]], rsa_keypair: RSAPrivateKey) -> None:
        """Verify a properly signed JWT with valid claims.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        :param rsa_keypair: Generated RSA private/public key pair.
        :type rsa_keypair: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        access_token = "test_access_token_123"
        at_hash = _compute_at_hash(access_token)

        now = datetime.now(UTC)
        payload = {
            "iss": base_url,
            "sub": "user123",
            "aud": handler._config_mgr.client_id,
            "exp": (now + timedelta(hours=1)).timestamp(),
            "iat": now.timestamp(),
            "nbf": (now - timedelta(seconds=5)).timestamp(),
            "nonce": "test_nonce",
            "email": "test@example.com",
            "name": "Test User",
            "at_hash": at_hash,
        }

        id_token = _sign_jwt(rsa_keypair, payload)

        # Call __verify_token_exchange via authenticate flow indirectly,
        # or call it directly through name mangling
        result = await handler._AuthenticationHandler__verify_token_exchange(
            discovery, id_token, access_token
        )
        assert result["sub"] == "user123"
        assert result["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_verify_token_without_at_hash(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]], rsa_keypair: RSAPrivateKey) -> None:
        """Token without at_hash should still be valid.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        :param rsa_keypair: Generated RSA private/public key pair.
        :type rsa_keypair: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        now = datetime.now(UTC)
        payload = {
            "iss": base_url,
            "sub": "user456",
            "aud": handler._config_mgr.client_id,
            "exp": (now + timedelta(hours=1)).timestamp(),
            "iat": now.timestamp(),
            "nbf": (now - timedelta(seconds=5)).timestamp(),
        }

        id_token = _sign_jwt(rsa_keypair, payload)
        result = await handler._AuthenticationHandler__verify_token_exchange(
            discovery, id_token, "any_access_token"
        )
        assert result["sub"] == "user456"

    @pytest.mark.asyncio
    async def test_verify_token_at_hash_mismatch(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]], rsa_keypair: RSAPrivateKey) -> None:
        """Token with wrong at_hash should raise.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        :param rsa_keypair: Generated RSA private/public key pair.
        :type rsa_keypair: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        now = datetime.now(UTC)
        payload = {
            "iss": base_url,
            "sub": "user789",
            "aud": handler._config_mgr.client_id,
            "exp": (now + timedelta(hours=1)).timestamp(),
            "iat": now.timestamp(),
            "nbf": (now - timedelta(seconds=5)).timestamp(),
            "at_hash": "wrong_hash_value",
        }

        id_token = _sign_jwt(rsa_keypair, payload)
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await handler._AuthenticationHandler__verify_token_exchange(
                discovery, id_token, "test_access_token"
            )


class TestExchangeCode:
    """Tests for the authorization code exchange flow."""

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]], rsa_keypair: RSAPrivateKey) -> None:
        """Successful code exchange returns verified id_token payload.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        :param rsa_keypair: Generated RSA private/public key pair.
        :type rsa_keypair: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        access_token = "returned_access_token"
        at_hash = _compute_at_hash(access_token)

        now = datetime.now(UTC)
        payload = {
            "iss": base_url,
            "sub": "exchanged_user",
            "aud": handler._config_mgr.client_id,
            "exp": (now + timedelta(hours=1)).timestamp(),
            "iat": now.timestamp(),
            "nbf": (now - timedelta(seconds=5)).timestamp(),
            "nonce": "exchange_nonce",
            "email": "exchanged@example.com",
            "at_hash": at_hash,
        }
        id_token = _sign_jwt(rsa_keypair, payload)

        token_response = {
            "id_token": id_token,
            "access_token": access_token,
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        httpserver.expect_request("/token", method="POST").respond_with_json(token_response)

        result_payload, result_at, result_exp = await handler._AuthenticationHandler__exchange_code("auth_code_123")
        assert result_payload["sub"] == "exchanged_user"
        assert result_payload["email"] == "exchanged@example.com"
        assert result_at == access_token
        assert result_exp == 3600

    @pytest.mark.asyncio
    async def test_exchange_code_http_error(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]]) -> None:
        """Non-200 response from token endpoint should raise.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        """
        httpserver, _ = oidc_server

        httpserver.expect_request("/token", method="POST").respond_with_data(
            "Unauthorized", status=401
        )

        with pytest.raises(Exception, match="Non-Zero HTTP Status: 401"):
            await handler._AuthenticationHandler__exchange_code("bad_code")


class TestFullAuthenticateFlow:
    """Test the full authenticate() method with a local OIDC server."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]], rsa_keypair: RSAPrivateKey) -> None:
        """Full successful authentication flow.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        :param rsa_keypair: Generated RSA private/public key pair.
        :type rsa_keypair: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        nonce = "test_nonce_value"
        access_token = "full_flow_access_token"
        at_hash = _compute_at_hash(access_token)

        now = datetime.now(UTC)
        id_payload = {
            "iss": base_url,
            "sub": "full_flow_user",
            "aud": handler._config_mgr.client_id,
            "exp": (now + timedelta(hours=1)).timestamp(),
            "iat": now.timestamp(),
            "nbf": (now - timedelta(seconds=5)).timestamp(),
            "nonce": nonce,
            "email": "fullflow@example.com",
            "name": "Full Flow",
            "at_hash": at_hash,
        }
        id_token = _sign_jwt(rsa_keypair, id_payload)

        token_response = {
            "id_token": id_token,
            "access_token": access_token,
            "expires_in": 3600,
        }

        httpserver.expect_request("/token", method="POST").respond_with_json(token_response)

        # Build state matching the format from _generate_redirect_params
        state_value = quote(urlencode({
            "sec": "fakesecurityhash",
            "redirect": str(handler._config_mgr.redirect_url),
            "start": "/dashboard",
        }))

        cookies = {
            "auth_nonce": nonce,
            "auth_state": state_value,
        }
        query_params = {
            "state": state_value,
            "code": "auth_code_full",
        }

        response, identity = await handler.authenticate(cookies, query_params)
        assert response.status_code == 302
        assert identity["id"]["sub"] == "full_flow_user"
        assert identity["id"]["email"] == "fullflow@example.com"
        assert identity["at"] == access_token
        assert identity["exp"] == 3600

    @pytest.mark.asyncio
    async def test_authenticate_nonce_mismatch(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]], rsa_keypair: RSAPrivateKey) -> None:
        """Nonce mismatch between cookie and id_token should raise.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        :param rsa_keypair: Generated RSA private/public key pair.
        :type rsa_keypair: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        access_token = "nonce_mismatch_token"
        at_hash = _compute_at_hash(access_token)

        now = datetime.now(UTC)
        id_payload = {
            "iss": base_url,
            "sub": "replay_user",
            "aud": handler._config_mgr.client_id,
            "exp": (now + timedelta(hours=1)).timestamp(),
            "iat": now.timestamp(),
            "nbf": (now - timedelta(seconds=5)).timestamp(),
            "nonce": "token_nonce",  # Different from cookie nonce
            "at_hash": at_hash,
        }
        id_token = _sign_jwt(rsa_keypair, id_payload)

        token_response = {
            "id_token": id_token,
            "access_token": access_token,
            "expires_in": 3600,
        }

        httpserver.expect_request("/token", method="POST").respond_with_json(token_response)

        state = "matching_state"
        cookies = {
            "auth_nonce": "cookie_nonce",  # Different from token nonce
            "auth_state": state,
        }
        query_params = {
            "state": state,
            "code": "replay_code",
        }

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await handler.authenticate(cookies, query_params)


class TestAuthConfig:
    """Additional tests for AuthConfig to cover config caching and errors."""

    @pytest.mark.asyncio
    async def test_config_caches_result(self, oidc_server: tuple[HTTPServer, dict[str, object]]) -> None:
        """Config should be cached and not re-fetched within TTL.

        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        """
        httpserver, discovery = oidc_server
        base_url = httpserver.url_for("").rstrip("/")

        cfg = AuthConfig(
            site_root=base_url,
            var_prefix=TEST_ENV_VAR_PREFIX,
            update_interval=timedelta(hours=1),  # Long TTL
        )

        result1 = await cfg.config()
        result2 = await cfg.config()

        assert result1 == result2
        assert result1["issuer"] == base_url

    @pytest.mark.asyncio
    async def test_config_error_on_bad_status(self, local_httpserver: HTTPServer) -> None:
        """Non-200 from well-known endpoint should raise.

        :param local_httpserver: Local HTTP test server.
        :type local_httpserver: HTTPServer
        """
        local_httpserver.expect_request(
            "/.well-known/openid-configuration"
        ).respond_with_data("Not Found", status=404)

        base_url = local_httpserver.url_for("").rstrip("/")
        cfg = AuthConfig(
            site_root=base_url,
            var_prefix=TEST_ENV_VAR_PREFIX,
        )

        with pytest.raises(Exception, match="wellknown config returned: 404"):
            await cfg.config()


class TestLoginFlow:
    """Additional login flow tests."""

    @pytest.mark.asyncio
    async def test_login_redirect_contains_nonce(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]]) -> None:
        """Login redirect should include nonce in query params.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        """
        response = await handler.login("/home", scopes={"openid", "email"})
        location = dict(response.raw_headers).get(b"location", b"").decode()
        assert "nonce=" in location

    @pytest.mark.asyncio
    async def test_login_redirect_contains_redirect_uri(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]]) -> None:
        """Login redirect should include the configured redirect URI.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        """
        response = await handler.login("/home")
        location = dict(response.raw_headers).get(b"location", b"").decode()
        assert "redirect_uri=" in location

    @pytest.mark.asyncio
    async def test_generate_redirect_params(self, handler: ConcreteAuthHandler, oidc_server: tuple[HTTPServer, dict[str, object]]) -> None:
        """Verify _generate_redirect_params returns all required OIDC params.

        :param handler: Authentication handler under test.
        :type handler: ConcreteAuthHandler
        :param oidc_server: Local OIDC server and discovery document.
        :type oidc_server: tuple
        """
        params = await handler._generate_redirect_params("/start", {"openid", "profile"})
        assert "response_type" in params
        assert params["response_type"] == "code"
        assert "client_id" in params
        assert "state" in params
        assert "nonce" in params
        assert "redirect_uri" in params
        assert "scope" in params
