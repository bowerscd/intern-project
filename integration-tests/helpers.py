"""Shared helpers for integration tests.

Provides reusable OIDC registration functions so that individual test
modules don't duplicate the multi-step flow.
"""

from __future__ import annotations

import http.cookiejar as cookielib

import httpx
from urllib.parse import urlparse, parse_qs, urlencode


class _PermissiveCookiePolicy(cookielib.DefaultCookiePolicy):
    """Cookie policy that unconditionally accepts and returns all cookies.

    ``http.cookiejar.DefaultCookiePolicy`` applies RFC 2965
    effective-host-name rules that silently drop ``Set-Cookie`` values for
    bare hostnames such as ``localhost`` (it appends ``.local`` to the
    effective request host, causing a domain mismatch on the send path).

    This policy disables those checks so that **every** ``Set-Cookie`` is
    stored and **every** stored cookie is sent back, which is the behaviour
    we need for integration tests that talk to ``http://localhost:…``.
    """

    def set_ok(self, cookie, request):  # noqa: ARG002
        return True

    def return_ok(self, cookie, request):  # noqa: ARG002
        return True


def create_backend_client(base_url: str, **kwargs) -> httpx.Client:
    """Create an :class:`httpx.Client` with permissive cookie handling.

    Replaces the default ``http.cookiejar`` cookie policy with
    :class:`_PermissiveCookiePolicy` so that cookies for bare hostnames
    like ``localhost`` are stored and resent correctly.
    """
    kwargs.setdefault("follow_redirects", False)
    kwargs.setdefault("timeout", 10.0)
    client = httpx.Client(base_url=base_url, **kwargs)
    client.cookies.jar._policy = _PermissiveCookiePolicy()
    return client


def rewrite_oidc_url(url: str, oidc_issuer: str) -> str:
    """Rewrite a Docker-internal OIDC URL to be reachable from the test host.

    In Docker mode the backend's OIDC issuer (e.g. ``http://oidc:9000``) is
    unreachable from the test runner on the host.  This helper rewrites the
    authority portion so the URL points to the published port that the test
    runner *can* reach (e.g. ``http://localhost:9000``).

    In local mode the URL is already reachable, so it is returned unchanged.
    """
    parsed = urlparse(url)
    issuer_parsed = urlparse(oidc_issuer)
    if parsed.netloc != issuer_parsed.netloc:
        return url.replace(
            f"{parsed.scheme}://{parsed.netloc}",
            oidc_issuer,
            1,
        )
    return url


def oidc_register_session(
    backend_url: str,
    oidc_issuer: str,
    *,
    sub: str,
    name: str,
    email: str,
) -> httpx.Client:
    """Drive the OIDC registration flow and return a client with a pending session.

    The returned :class:`httpx.Client` has completed the OIDC callback
    in register mode and has ``pending_registration`` stored in the
    server-side session.  It has **not** called ``/complete-registration``
    or ``/claim-account`` yet.

    :param backend_url: Base URL of the backend (e.g. ``http://127.0.0.1:8000``).
    :param oidc_issuer: Base URL of the mock OIDC provider.
    :param sub: OIDC ``sub`` claim for the test user.
    :param name: Display name for the test user.
    :param email: Email address for the test user.
    :returns: An httpx client with cookies from the OIDC callback.
    """
    client = create_backend_client(backend_url)

    # 1. Initiate registration
    resp = client.get("/api/v2/auth/register/test")
    assert resp.status_code in (302, 307)
    authorize_url = resp.headers["location"]

    # 2. Follow the redirect to the mock OIDC authorize page
    #    The backend may redirect to a Docker-internal URL (e.g. http://oidc:9000)
    #    that is unreachable from the test host; rewrite if needed.
    authorize_url = rewrite_oidc_url(authorize_url, oidc_issuer)
    resp = httpx.get(authorize_url, follow_redirects=False, timeout=10.0)
    assert resp.status_code == 200

    # 3. Approve the OIDC request (simulate the user clicking Authorize)
    parsed = urlparse(authorize_url)
    qs = parse_qs(parsed.query)
    approve_url = f"{oidc_issuer}/authorize/approve?" + urlencode(
        {
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub,
            "name": name,
            "email": email,
        }
    )
    resp = httpx.get(approve_url, follow_redirects=False, timeout=10.0)
    assert resp.status_code == 302

    # 4. Hit the backend callback
    callback_url = resp.headers["location"]
    cb_parsed = urlparse(callback_url)
    resp = client.get(f"{cb_parsed.path}?{cb_parsed.query}")
    assert resp.status_code in (302, 307), (
        f"OIDC callback returned {resp.status_code}: {resp.text[:500]}"
    )

    return client


def complete_registration(client: httpx.Client, username: str) -> dict:
    """Complete registration on an already-authenticated OIDC session.

    Fetches a CSRF token, calls ``/complete-registration``, asserts
    success, and returns the response JSON.

    :param client: An httpx client with a ``pending_registration`` session.
    :param username: The desired username.
    :returns: The JSON response body from the registration endpoint.
    """
    csrf_resp = client.get("/api/v2/auth/csrf-token")
    csrf = csrf_resp.json()["csrf_token"]
    resp = client.post(
        "/api/v2/auth/complete-registration",
        json={"username": username},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201, (
        f"{resp.text[:300]}  ||  client_cookies={list(client.cookies.keys())}"
    )
    return resp.json()


def register_user(
    backend_url: str,
    oidc_issuer: str,
    *,
    sub: str,
    name: str,
    email: str,
    username: str,
) -> httpx.Client:
    """Drive OIDC registration through to a fully authenticated session.

    Combines :func:`oidc_register_session` and :func:`complete_registration`
    into a single call.  Returns an httpx client with a valid session cookie.

    :param backend_url: Base URL of the backend.
    :param oidc_issuer: Base URL of the mock OIDC provider.
    :param sub: OIDC ``sub`` claim for the test user.
    :param name: Display name for the test user.
    :param email: Email address for the test user.
    :param username: The desired username for registration.
    :returns: An httpx client with a fully authenticated session.
    """
    client = oidc_register_session(
        backend_url,
        oidc_issuer,
        sub=sub,
        name=name,
        email=email,
    )
    complete_registration(client, username)
    return client
