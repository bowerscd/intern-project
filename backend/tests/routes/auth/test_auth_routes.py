"""Tests for auth route endpoints (login and callback)."""
import json
from hashlib import sha256
from base64 import urlsafe_b64encode
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from jwt import encode as jwt_encode
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


from models import ExternalAuthProvider
from db import Database
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def _make_rsa_keypair() -> RSAPrivateKey:
    """Generate an RSA private key for JWT signing.
    
        :returns: An RSA private key.
        :rtype: rsa.RSAPrivateKey
    """
    return rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )


def _key_to_jwk(private_key: RSAPrivateKey) -> dict:
    """Convert an RSA public key to JWK dict.

    :param private_key: RSA private key.
    :type private_key: rsa.RSAPrivateKey
    :returns: A JWK-formatted dictionary.
    :rtype: dict
    """
    from jwt.algorithms import RSAAlgorithm
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk_dict["kid"] = "test-key-1"
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"
    return jwk_dict


def _sign_jwt(private_key: RSAPrivateKey, payload: dict) -> str:
    """Sign a JWT payload with the given private key.

    :param private_key: RSA private key.
    :type private_key: rsa.RSAPrivateKey
    :param payload: JWT claims.
    :type payload: dict
    :returns: Encoded JWT string.
    :rtype: str
    """
    return jwt_encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key-1"})


def _compute_at_hash(access_token: str) -> str:
    """Compute the OIDC ``at_hash`` for an access token.

    :param access_token: The raw access token string.
    :type access_token: str
    :returns: Base64url-encoded half-hash.
    :rtype: str
    """
    digest = sha256(access_token.encode()).digest()
    half = digest[: len(digest) // 2]
    return urlsafe_b64encode(half).rstrip(b"=").decode()


class TestLoginRoute:
    """Test GET /api/v2/auth/login/{provider}."""

    def test_login_redirects(self, client: TestClient) -> None:
        """Login with test provider should redirect to authorization endpoint.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        # The auth handler's login will try to fetch well-known config,
        # so we mock the handler's login method
        from routes.auth import AuthMgrs
        from starlette.responses import RedirectResponse
        from http import HTTPStatus

        mock_response = RedirectResponse("https://accounts.localhost/auth", HTTPStatus.FOUND)

        original = AuthMgrs.get("test")
        if original:
            with patch.object(original, 'login', new_callable=AsyncMock, return_value=mock_response):
                response = client.get(
                    "/api/v2/auth/login/test",
                    follow_redirects=False,
                )
                assert response.status_code == 302

    def test_login_invalid_provider(self, client: TestClient) -> None:
        """Invalid provider should return 422.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        response = client.get(
            "/api/v2/auth/login/invalid_provider",
            follow_redirects=False,
        )
        assert response.status_code == 422


class TestCallbackRoute:
    """Test GET /api/v2/auth/callback/{provider}."""

    def test_callback_creates_pending_registration(self, client: TestClient, database: Database) -> None:
        """Successful callback with mode=register should store pending_registration in session.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from routes.auth import AuthMgrs
        from starlette.responses import RedirectResponse
        from http import HTTPStatus

        mock_redirect = RedirectResponse("/dashboard", HTTPStatus.FOUND)
        mock_identity = {
            "id": {
                "sub": "unique_test_id_123",
                "email": "newuser@example.com",
                "name": "New User",
            },
            "at": "access_token_abc",
            "exp": 3600,
            "mode": "register",
        }

        original = AuthMgrs.get("test")
        if original:
            with patch.object(
                original, 'authenticate',
                new_callable=AsyncMock,
                return_value=(mock_redirect, mock_identity),
            ):
                client.cookies = {"auth_state": "test_state", "auth_nonce": "test_nonce"}
                response = client.get(
                    "/api/v2/auth/callback/test",
                    params={"code": "auth_code_123", "state": "test_state"},
                    follow_redirects=False,
                )
                # Should redirect without creating an account
                assert response.status_code == 302

    def test_callback_rejects_unknown_on_login(self, client: TestClient, database: Database) -> None:
        """Callback with mode=login (default) should reject unknown users with 403.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from routes.auth import AuthMgrs
        from starlette.responses import RedirectResponse
        from http import HTTPStatus

        mock_redirect = RedirectResponse("/dashboard", HTTPStatus.FOUND)
        mock_identity = {
            "id": {
                "sub": "unknown_user_id",
                "email": "unknown@example.com",
                "name": "Unknown User",
            },
            "at": "access_token_abc",
            "exp": 3600,
            "mode": "login",
        }

        original = AuthMgrs.get("test")
        if original:
            with patch.object(
                original, 'authenticate',
                new_callable=AsyncMock,
                return_value=(mock_redirect, mock_identity),
            ):
                client.cookies = {"auth_state": "test_state", "auth_nonce": "test_nonce"}
                response = client.get(
                    "/api/v2/auth/callback/test",
                    params={"code": "auth_code_123", "state": "test_state"},
                    follow_redirects=False,
                )
                assert response.status_code == 403

    def test_callback_existing_account(self, client: TestClient, database: Database) -> None:
        """Callback for existing user should find account, not create new.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from routes.auth import AuthMgrs
        from starlette.responses import RedirectResponse
        from http import HTTPStatus
        from db.functions import create_account

        # Pre-create the account
        with database.session() as s:
            act = create_account(
                "existing", "existing@example.com",
                ExternalAuthProvider.test, "existing_ext_id",
            )
            s.add(act)
            s.commit()

        mock_redirect = RedirectResponse("/home", HTTPStatus.FOUND)
        mock_identity = {
            "id": {
                "sub": "existing_ext_id",
                "email": "existing@example.com",
                "name": "Existing User",
            },
            "at": "at_existing",
            "exp": 3600,
            "mode": "login",
        }

        original = AuthMgrs.get("test")
        if original:
            with patch.object(
                original, 'authenticate',
                new_callable=AsyncMock,
                return_value=(mock_redirect, mock_identity),
            ):
                client.cookies = {"auth_state": "state_2", "auth_nonce": "nonce_2"}
                response = client.get(
                    "/api/v2/auth/callback/test",
                    params={"code": "code_2", "state": "state_2"},
                    follow_redirects=False,
                )
                assert response.status_code == 302

    def test_callback_invalid_provider(self, client: TestClient) -> None:
        """Invalid provider should return 422.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        client.cookies = {"auth_state": "y", "auth_nonce": "z"}
        response = client.get(
            "/api/v2/auth/callback/invalid",
            params={"code": "x", "state": "y"},
            follow_redirects=False,
        )
        assert response.status_code == 422

    def test_callback_missing_cookies(self, client: TestClient) -> None:
        """Missing cookies should return 422.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        response = client.get(
            "/api/v2/auth/callback/test",
            params={"code": "x", "state": "y"},
            follow_redirects=False,
        )
        assert response.status_code == 422

    def test_callback_register_existing_account_returns_409(self, client: TestClient, database: Database) -> None:
        """Registration callback for already-existing user should return 409.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from routes.auth import AuthMgrs
        from starlette.responses import RedirectResponse
        from http import HTTPStatus
        from db.functions import create_account

        # Pre-create the account
        with database.session() as s:
            act = create_account(
                "dupeuser", "dupe@example.com",
                ExternalAuthProvider.test, "dupe_ext_id",
            )
            s.add(act)
            s.commit()

        mock_redirect = RedirectResponse("/dashboard", HTTPStatus.FOUND)
        mock_identity = {
            "id": {
                "sub": "dupe_ext_id",
                "email": "dupe@example.com",
                "name": "Dupe User",
            },
            "at": "access_token_dupe",
            "exp": 3600,
            "mode": "register",
        }

        original = AuthMgrs.get("test")
        if original:
            with patch.object(
                original, 'authenticate',
                new_callable=AsyncMock,
                return_value=(mock_redirect, mock_identity),
            ):
                client.cookies = {"auth_state": "state_dup", "auth_nonce": "nonce_dup"}
                response = client.get(
                    "/api/v2/auth/callback/test",
                    params={"code": "code_dup", "state": "state_dup"},
                    follow_redirects=False,
                )
                assert response.status_code == 409


class TestRegisterRoute:
    """Test GET /api/v2/auth/register/{provider}."""

    def test_register_redirects(self, client: TestClient) -> None:
        """Register with test provider should redirect to authorization endpoint.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        from routes.auth import AuthMgrs
        from starlette.responses import RedirectResponse
        from http import HTTPStatus

        mock_response = RedirectResponse("https://accounts.localhost/auth", HTTPStatus.FOUND)

        original = AuthMgrs.get("test")
        if original:
            with patch.object(original, 'login', new_callable=AsyncMock, return_value=mock_response) as mock_login:
                response = client.get(
                    "/api/v2/auth/register/test",
                    follow_redirects=False,
                )
                assert response.status_code == 302
                # Verify mode="register" was passed
                mock_login.assert_called_once()
                call_kwargs = mock_login.call_args
                assert call_kwargs[1].get("mode") == "register" or (len(call_kwargs[0]) >= 3 and call_kwargs[0][2] == "register")

    def test_register_invalid_provider(self, client: TestClient) -> None:
        """Invalid provider should return 422.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        """
        response = client.get(
            "/api/v2/auth/register/invalid_provider",
            follow_redirects=False,
        )
        assert response.status_code == 422


class TestCompleteRegistration:
    """Test POST /api/v2/auth/complete-registration."""

    @staticmethod
    def _set_pending_session(client: TestClient, pending: dict) -> None:
        """Inject a ``pending_registration`` value into the client session.

        Uses the signed-session cookie mechanism from the app.
        """
        from json import dumps
        from base64 import b64encode
        from http.cookiejar import Cookie
        from datetime import datetime, UTC, timedelta
        from itsdangerous import TimestampSigner
        from routes import SESSION_COOKIE_NAME
        from routes.auth.authenticate import PENDING_REGISTRATION_KEY
        from app import secret

        payload = {PENDING_REGISTRATION_KEY: pending}
        signer = TimestampSigner(secret_key=str(secret))
        signed = signer.sign(b64encode(dumps(payload).encode("utf-8"))).decode("utf-8")

        cookie = Cookie(
            version=0, name=SESSION_COOKIE_NAME, value=signed,
            port=None, port_specified=False,
            domain="", domain_specified=False, domain_initial_dot=False,
            path="/", path_specified=True, secure=False,
            expires=(datetime.now(UTC) + timedelta(seconds=3600)).timestamp(),
            discard=True, comment=None, comment_url=None,
            rest={"HttpOnly": True, "SameSite": "lax"}, rfc2109=False,
        )
        client.cookies.jar.set_cookie(cookie)

    def test_complete_registration_success(self, client: TestClient, database: Database) -> None:
        """A user with a pending registration can pick a username and create an account.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        self._set_pending_session(client, {
            "provider": "test",
            "sub": "new_sub_1",
            "name": "Test User",
            "email": "test@example.com",
        })

        r = client.post("/api/v2/auth/complete-registration", json={"username": "myuser"})
        assert r.status_code == 201
        data = r.json()
        assert data["username"] == "myuser"
        assert "id" in data

    def test_complete_registration_duplicate_username(self, client: TestClient, database: Database) -> None:
        """Picking a username that already exists should return 409.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from db.functions import create_account

        with database.session() as s:
            act = create_account("taken", None, ExternalAuthProvider.test, "existing_sub")
            s.add(act)
            s.commit()

        self._set_pending_session(client, {
            "provider": "test",
            "sub": "new_sub_2",
            "name": "Another User",
            "email": None,
        })

        r = client.post("/api/v2/auth/complete-registration", json={"username": "taken"})
        assert r.status_code == 409

    def test_complete_registration_no_pending(self, client: TestClient, database: Database) -> None:
        """Without a pending registration session, should return 401.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        r = client.post("/api/v2/auth/complete-registration", json={"username": "someone"})
        assert r.status_code == 401

    def test_complete_registration_invalid_username(self, client: TestClient, database: Database) -> None:
        """An invalid username should be rejected by the schema validator.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        self._set_pending_session(client, {
            "provider": "test",
            "sub": "new_sub_3",
            "name": "Bad Name",
            "email": None,
        })

        r = client.post("/api/v2/auth/complete-registration", json={"username": ""})
        assert r.status_code == 422

        r = client.post("/api/v2/auth/complete-registration", json={"username": "a" * 37})
        assert r.status_code == 422

        r = client.post("/api/v2/auth/complete-registration", json={"username": "has spaces"})
        assert r.status_code == 422


class TestClaimAccount:
    """Test POST /api/v2/auth/claim-account."""

    @staticmethod
    def _set_pending_session(client: TestClient, pending: dict) -> None:
        """Inject a ``pending_registration`` value into the client session."""
        TestCompleteRegistration._set_pending_session(client, pending)

    def test_claim_account_success(self, client: TestClient, database: Database) -> None:
        """A user can submit a claim for an existing legacy account.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from db.functions import create_account

        with database.session() as s:
            act = create_account("legacyuser", None, ExternalAuthProvider.test, "legacy_ext")
            s.add(act)
            s.commit()

        self._set_pending_session(client, {
            "provider": "test",
            "sub": "claimer_sub_1",
            "name": "Claimer",
            "email": "claimer@example.com",
        })

        r = client.post("/api/v2/auth/claim-account", json={"username": "legacyuser"})
        assert r.status_code == 202
        data = r.json()
        assert data["status"] == "pending"
        assert "claim_id" in data

    def test_claim_nonexistent_account(self, client: TestClient, database: Database) -> None:
        """Claiming a non-existent username should return 404.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        self._set_pending_session(client, {
            "provider": "test",
            "sub": "claimer_sub_2",
            "name": "Nobody",
            "email": None,
        })

        r = client.post("/api/v2/auth/claim-account", json={"username": "doesnotexist"})
        assert r.status_code == 404

    def test_claim_no_pending(self, client: TestClient, database: Database) -> None:
        """Without a pending registration session, should return 401.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        r = client.post("/api/v2/auth/claim-account", json={"username": "someone"})
        assert r.status_code == 401

    def test_duplicate_claim_rejected(self, client: TestClient, database: Database) -> None:
        """Submitting a duplicate pending claim should return 409.

        :param client: Unauthenticated HTTP test client.
        :type client: TestClient
        :param database: Started database instance.
        :type database: Database
        """
        from db.functions import create_account

        with database.session() as s:
            act = create_account("dupetarget", None, ExternalAuthProvider.test, "dupe_target_ext")
            s.add(act)
            s.commit()

        pending = {
            "provider": "test",
            "sub": "claimer_sub_dup",
            "name": "Dup Claimer",
            "email": None,
        }

        self._set_pending_session(client, pending)
        r = client.post("/api/v2/auth/claim-account", json={"username": "dupetarget"})
        assert r.status_code == 202

        # Re-set the pending session (it may have been consumed)
        self._set_pending_session(client, pending)
        r = client.post("/api/v2/auth/claim-account", json={"username": "dupetarget"})
        assert r.status_code == 409
