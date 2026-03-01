"""Backend-for-Frontend OIDC authentication handler."""

from typing import Set, Any, Dict, Tuple, List

from starlette.datastructures import URL
from starlette.responses import RedirectResponse
from fastapi import HTTPException, status

from .config import AuthConfig


def _make_auth_cookie(
    response: RedirectResponse, key: str, val: str, duration_in_seconds: int = 60 * 5
) -> None:
    """Create a secure cookie with correct RFC attributes on a redirect response.

    :param response: The redirect response to attach the cookie to.
    :param key: Cookie name.
    :param val: Cookie value.
    :param duration_in_seconds: Cookie max-age in seconds (default 300).
    """
    from config import DEV_MODE

    response.set_cookie(
        key,
        val,
        max_age=duration_in_seconds,
        path="/",
        secure=not DEV_MODE,
        httponly=True,
        samesite="lax",
    )


class AuthenticationHandler:
    """Backend-for-Frontend (BFF) authentication handler.

    Manages the complete OIDC authorisation-code flow including redirect
    generation, token exchange, ID-token verification and session
    establishment.
    """

    __RANDOM_BITS = 4096

    def __init__(self, config: AuthConfig) -> None:
        """Initialise the handler with an OIDC configuration manager.

        :param config: The :class:`AuthConfig` instance providing client
            credentials and well-known endpoint discovery.
        """
        self._config_mgr: AuthConfig = config
        self._state_cookie_key = "auth_state"
        self._nonce_cookie_key = "auth_nonce"

    async def __verify_token_exchange(
        self, config: Dict[str, str], id_token: str, access_token: str
    ) -> Dict[str, str]:
        """Verify an ID token obtained from an authorisation-code exchange.

        Validates the token's signature, audience, expiry, and ``at_hash``
        claim.

        :param config: The OIDC provider's well-known configuration dict.
        :param id_token: The raw ID token JWT.
        :param access_token: The raw access token used for ``at_hash``
            verification.
        :returns: The decoded ID-token payload.
        :rtype: Dict[str, str]
        :raises Exception: If the ``at_hash`` does not match the access
            token.
        """
        from jwt import PyJWKClient, decode_complete, get_algorithm_by_name
        from base64 import urlsafe_b64encode
        from datetime import timedelta

        VERIFY_OPTIONS = {
            "verify_aud": True,
            "verify_exp": True,
            "verify_iat": True,
            "verify_nbf": True,
        }

        jwk_client = PyJWKClient(config["jwks_uri"])

        key = jwk_client.get_signing_key_from_jwt(id_token)
        # Only allow well-known signing algorithms
        _ALLOWED_SIGNING_ALGOS = {
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "PS256",
            "PS384",
            "PS512",
        }
        sign_algos = [
            a
            for a in config.get("id_token_signing_alg_values_supported", [])
            if a in _ALLOWED_SIGNING_ALGOS
        ]
        if not sign_algos:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        data: Any = decode_complete(
            id_token,
            key,
            sign_algos,
            audience=self._config_mgr.client_id,
            issuer=config["issuer"],
            options=VERIFY_OPTIONS,
            leeway=timedelta(seconds=5),
        )

        payload: Dict[str, str] = data["payload"]
        header: Dict[str, str] = data["header"]

        token_at_hash = payload.get("at_hash")

        if token_at_hash is None:
            return payload

        token_at_hash = token_at_hash.encode()

        alg_obj = get_algorithm_by_name(header["alg"])
        digest = alg_obj.compute_hash_digest(access_token.encode())
        at_hash = urlsafe_b64encode(digest[: (len(digest) // 2)]).rstrip(b"=")

        if at_hash != token_at_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        return payload

    async def __exchange_code(self, code: str) -> Tuple[Dict[str, str], str, int]:
        """Exchange an authorisation code for tokens and verify the ID token.

        :param code: The authorisation code received from the OIDC provider.
        :returns: A tuple of ``(id_token_payload, access_token, expires_in)``.
        :rtype: Tuple[Dict[str, str], str, int]
        :raises Exception: If the token endpoint returns a non-200 status.
        """
        from http import HTTPStatus
        from aiohttp import ClientSession, ClientTimeout

        config = await self._config_mgr.config()

        request_data: Dict[str, str] = {
            "code": code,
            "client_id": self._config_mgr.client_id,
            "client_secret": self._config_mgr.secret,
            "redirect_uri": f"{self._config_mgr.redirect_url}",
            "grant_type": "authorization_code",
        }

        async with ClientSession(timeout=ClientTimeout(total=10)) as s:
            r = await s.post(config["token_endpoint"], data=request_data)
            if r.status != HTTPStatus.OK:
                raise Exception(f"Non-Zero HTTP Status: {r.status}")

            response = await r.json()

        id_token = response["id_token"]
        access_token = response["access_token"]
        expiry = response["expires_in"]

        id_token_payload = await self.__verify_token_exchange(
            config, id_token, access_token
        )

        return id_token_payload, access_token, expiry

    async def authenticate(
        self, cookies: Dict[str, str], query_params: Dict[str, str]
    ) -> Tuple[RedirectResponse, Dict[str, Dict[str, str] | str | int]]:
        """Complete an OIDC callback, returning the redirect and token payload.

        Validates anti-CSRF state and nonce cookies, exchanges the
        authorisation code, and verifies the resulting ID token.

        :param cookies: Cookies from the callback request (must include
            ``auth_state`` and ``auth_nonce``).
        :param query_params: Query parameters from the callback request
            (must include ``state`` and ``code``).
        :returns: A tuple of ``(redirect_response, identity_dict)``.
        :rtype: Tuple[RedirectResponse, Dict[str, Dict[str, str] | str | int]]
        :raises Exception: On any forgery or replay-attack indicators.
        """
        from http import HTTPStatus
        from urllib.parse import unquote, parse_qs

        c_nonce = cookies.get(self._nonce_cookie_key)
        if c_nonce is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        c_state = cookies.get(self._state_cookie_key)
        if c_state is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        r_state = query_params.get("state")
        if r_state is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        import hmac

        if not hmac.compare_digest(r_state, c_state):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        r_state = parse_qs(unquote(r_state))

        exchange_code = query_params.get("code")
        if exchange_code is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        id_token, access_token, expiry = await self.__exchange_code(exchange_code)

        import hmac

        id_token_nonce = id_token.get("nonce")
        if id_token_nonce is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )
        if not hmac.compare_digest(id_token_nonce, c_nonce):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
            )

        start: List[str] = r_state.get("start", ["/account"])
        if not start or len(start) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid state parameter",
            )

        mode_list: List[str] = r_state.get("mode", ["login"])
        mode = mode_list[0] if mode_list else "login"

        response = RedirectResponse(unquote(start[0]), HTTPStatus.FOUND)
        response.delete_cookie(self._nonce_cookie_key)
        response.delete_cookie(self._state_cookie_key)

        return (
            response,
            {"id": id_token, "at": access_token, "exp": expiry, "mode": mode},
        )

    async def login(
        self, start: str, scopes: Set[str] = set(), mode: str = "login"
    ) -> RedirectResponse:
        """Start a login or registration workflow for the user.

        :param start: The URL to redirect to after authentication succeeds.
        :param scopes: OAuth2 scopes to request from the provider.
        :param mode: Workflow mode — ``"login"`` or ``"register"``.
        :returns: A redirect response to the OIDC provider.
        :rtype: RedirectResponse
        """
        return await self._redirect(start, scopes, mode)

    async def _generate_redirect_params(
        self, start: str, scopes: Set[str] = set(), mode: str = "login"
    ) -> Dict[str, str]:
        """Generate query parameters for an OIDC/OAuth2 authorisation request.

        Produces cryptographic state and nonce values to protect against
        CSRF and replay attacks.

        :param start: The URL to redirect to after authentication succeeds.
        :param scopes: OAuth2 scopes to request.
        :param mode: Workflow mode — ``"login"`` or ``"register"``.
        :returns: A dict of query-string parameters for the authorisation
            endpoint.
        :rtype: Dict[str, str]
        """
        from secrets import token_bytes
        from hashlib import sha384
        from urllib.parse import urlencode, quote

        state = quote(
            urlencode(
                {
                    "sec": sha384(
                        token_bytes(AuthenticationHandler.__RANDOM_BITS)
                    ).hexdigest(),
                    "redirect": f"{self._config_mgr.redirect_url}",
                    "start": start,
                    "mode": mode,
                }
            )
        )

        nonce = sha384(token_bytes(AuthenticationHandler.__RANDOM_BITS)).hexdigest()

        return {
            "response_type": "code",
            "client_id": self._config_mgr.client_id,
            "scope": " ".join(scopes),
            "redirect_uri": f"{self._config_mgr.redirect_url}",
            "state": state,
            "nonce": nonce,
        }

    async def _redirect(
        self, start: str, scopes: Set[str] = set(), mode: str = "login"
    ) -> RedirectResponse:
        """Build and return the OIDC redirect response.

        Sets the anti-CSRF ``state`` and ``nonce`` cookies on the response.

        :param start: The URL to redirect to after authentication succeeds.
        :param scopes: OAuth2 scopes to request.
        :param mode: Workflow mode — ``"login"`` or ``"register"``.
        :returns: A 302 redirect response to the provider's authorisation
            endpoint.
        :rtype: RedirectResponse
        """
        from http import HTTPStatus

        config = await self._config_mgr.config()
        host: URL = URL(config["authorization_endpoint"])

        params = await self._generate_redirect_params(start, scopes, mode)

        target = host.replace_query_params(**params)
        response = RedirectResponse(target, HTTPStatus.FOUND)

        _make_auth_cookie(response, self._nonce_cookie_key, params["nonce"])
        _make_auth_cookie(response, self._state_cookie_key, params["state"])

        return response
