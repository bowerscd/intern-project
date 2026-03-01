#!/usr/bin/env python3
"""Minimal OIDC provider for integration tests.

Implements the full Authorization Code flow so the backend's ``test`` provider
exercises 100% of the real authentication code path — redirect, anti-CSRF
cookies, token exchange, JWT signature verification, ``at_hash`` validation —
with zero special-case branches in the application itself.

Can run standalone::

    python mock_oidc.py          # defaults to port 9000
    python mock_oidc.py 9001     # custom port

Or be started programmatically from ``conftest.py`` fixtures.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import sys
import threading
import time
from base64 import urlsafe_b64encode
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict
from urllib.parse import parse_qs, urlencode, urlparse

import jwt  # PyJWT
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = 9000
if __name__ == "__main__" and len(sys.argv) > 1:
    PORT = int(sys.argv[1])
CLIENT_ID = os.environ.get("TEST_CLIENT_ID", "client_id1")
CLIENT_SECRET = os.environ.get("TEST_CLIENT_SECRET", "definitely_a_secret")

# ---------------------------------------------------------------------------
# RSA key pair — generated once per process lifetime
# ---------------------------------------------------------------------------

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()
_pub_numbers = _public_key.public_numbers()
_kid = "mock-oidc-dev-key-1"


def _b64uint(value: int, length: int) -> str:
    """Encode an unsigned integer as unpadded URL-safe Base64."""
    return urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


_jwk_public: Dict[str, str] = {
    "kty": "RSA",
    "use": "sig",
    "alg": "RS256",
    "kid": _kid,
    "n": _b64uint(_pub_numbers.n, 256),
    "e": _b64uint(_pub_numbers.e, 3),
}

_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)

# ---------------------------------------------------------------------------
# In-memory authorization code store  {code: {nonce, redirect_uri, ...}}
# ---------------------------------------------------------------------------

_pending_codes: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _mint_id_token(
    issuer: str,
    sub: str,
    nonce: str,
    access_token: str,
    name: str = "Dev User",
    email: str = "dev@localhost",
) -> str:
    """Mint a signed ID token with all claims the backend verifies."""
    now = int(time.time())

    # at_hash: first half of SHA-256 of the access_token, base64url-encoded
    digest = hashlib.sha256(access_token.encode()).digest()
    at_hash = urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()

    payload = {
        "iss": issuer,
        "sub": sub,
        "aud": CLIENT_ID,
        "exp": now + 3600,
        "iat": now,
        "nbf": now - 5,
        "nonce": nonce,
        "at_hash": at_hash,
        "name": name,
        "email": email,
    }

    return jwt.encode(payload, _private_pem, algorithm="RS256", headers={"kid": _kid})


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------


def make_handler(issuer: str, external_issuer: str | None = None):
    """Factory: return a handler class bound to a specific issuer URL.

    *external_issuer*, when provided, is used for the
    ``authorization_endpoint`` in the well-known config so that a browser
    running **outside** the Docker network can reach the authorize page,
    while the ``token_endpoint`` (server-to-server) still uses *issuer*.
    """
    browser_issuer = external_issuer or issuer

    class OIDCHandler(BaseHTTPRequestHandler):
        """Handles the four OIDC endpoints the backend needs."""

        def _send_json(self, data: Any, code: int = 200) -> None:
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html_str: str, code: int = 200) -> None:
            body = html_str.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_redirect(self, url: str) -> None:
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/.well-known/openid-configuration":
                self._handle_well_known()
            elif path == "/jwks":
                self._handle_jwks()
            elif path == "/authorize":
                self._handle_authorize(qs)
            elif path == "/authorize/approve":
                self._handle_authorize_approve(qs)
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/token":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                params = parse_qs(body)
                self._handle_token(params)
            else:
                self.send_error(404)

        def _handle_well_known(self) -> None:
            self._send_json({
                "issuer": issuer,
                "authorization_endpoint": f"{browser_issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "jwks_uri": f"{issuer}/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "scopes_supported": ["openid", "email", "profile"],
            })

        def _handle_jwks(self) -> None:
            self._send_json({"keys": [_jwk_public]})

        def _handle_authorize(self, qs: Dict[str, list]) -> None:
            """Show a one-click login form."""
            redirect_uri = qs.get("redirect_uri", [""])[0]
            state = qs.get("state", [""])[0]
            nonce = qs.get("nonce", [""])[0]
            client_id = qs.get("client_id", [""])[0]

            if client_id != CLIENT_ID:
                self._send_html("<h1>Unknown client_id</h1>", 400)
                return

            self._send_html(f"""<!doctype html>
<html><head><title>Mock OIDC Login</title></head><body>
<h2>Mock OIDC Provider</h2>
<form method="GET" action="/authorize/approve">
  <input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri)}" />
  <input type="hidden" name="state" value="{html.escape(state)}" />
  <input type="hidden" name="nonce" value="{html.escape(nonce)}" />
  <label>Subject (sub)</label>
  <input name="sub" value="test-user-1" />
  <label>Display name</label>
  <input name="name" value="Integration User" />
  <label>Email</label>
  <input name="email" value="test@integration.local" />
  <button type="submit">Authorize</button>
</form>
</body></html>""")

        def _handle_authorize_approve(self, qs: Dict[str, list]) -> None:
            """Process approval and redirect with an auth code."""
            redirect_uri = qs.get("redirect_uri", [""])[0]
            state = qs.get("state", [""])[0]
            nonce = qs.get("nonce", [""])[0]
            sub = qs.get("sub", ["test-user-1"])[0]
            name = qs.get("name", ["Integration User"])[0]
            email_addr = qs.get("email", ["test@integration.local"])[0]

            code = secrets.token_urlsafe(32)
            _pending_codes[code] = {
                "nonce": nonce,
                "redirect_uri": redirect_uri,
                "sub": sub,
                "name": name,
                "email": email_addr,
            }

            sep = "&" if "?" in redirect_uri else "?"
            target = f"{redirect_uri}{sep}{urlencode({'code': code, 'state': state})}"
            self._send_redirect(target)

        def _handle_token(self, params: Dict[str, list]) -> None:
            """Exchange an authorization code for tokens."""
            code = params.get("code", [""])[0]
            client_id = params.get("client_id", [""])[0]
            client_secret = params.get("client_secret", [""])[0]
            grant_type = params.get("grant_type", [""])[0]

            if grant_type != "authorization_code":
                self._send_json({"error": "unsupported_grant_type"}, 400)
                return

            if client_id != CLIENT_ID or client_secret != CLIENT_SECRET:
                self._send_json({"error": "invalid_client"}, 401)
                return

            pending = _pending_codes.pop(code, None)
            if pending is None:
                self._send_json({"error": "invalid_grant"}, 400)
                return

            access_token = secrets.token_urlsafe(32)

            id_token = _mint_id_token(
                issuer=issuer,
                sub=pending["sub"],
                nonce=pending["nonce"],
                access_token=access_token,
                name=pending["name"],
                email=pending["email"],
            )

            self._send_json({
                "id_token": id_token,
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 3600,
            })

        def log_message(self, fmt: str, *args: Any) -> None:
            """Prefix log lines with [mock-oidc]."""
            sys.stderr.write(f"[mock-oidc] {fmt % args}\n")

    return OIDCHandler


# ---------------------------------------------------------------------------
# Programmatic start/stop (used by conftest fixtures)
# ---------------------------------------------------------------------------


def start_server(port: int = 0) -> tuple[HTTPServer, str, int]:
    """Start the mock OIDC provider on the given port (0 = random).

    :returns: (server, issuer_url, actual_port)
    """
    server = HTTPServer(("127.0.0.1", port), make_handler("PLACEHOLDER"))
    actual_port = server.server_address[1]
    issuer_url = f"http://127.0.0.1:{actual_port}"

    # Re-create handler with the actual issuer URL now that we know the port
    server.RequestHandlerClass = make_handler(issuer_url)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, issuer_url, actual_port


def stop_server(server: HTTPServer) -> None:
    """Shut down the mock OIDC server."""
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main() -> None:
    issuer = os.environ.get("MOCK_OIDC_ISSUER", f"http://localhost:{PORT}")
    external_issuer = os.environ.get("MOCK_OIDC_EXTERNAL_ISSUER")
    server = HTTPServer(("0.0.0.0", PORT), make_handler(issuer, external_issuer))
    print(f"[mock-oidc] Mock OIDC provider running at {issuer}")
    if external_issuer:
        print(f"[mock-oidc] External (browser) issuer: {external_issuer}")
    print(f"[mock-oidc] JWKS:      {issuer}/jwks")
    print(f"[mock-oidc] Authorize: {external_issuer or issuer}/authorize")
    print(f"[mock-oidc] Token:     {issuer}/token")
    print(f"[mock-oidc] Client ID: {CLIENT_ID}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock-oidc] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
