"""Integration tests for sidebar nav visibility.

The frontend renders every nav link in the server-side ``base.html`` template.
Links that require authentication or specific claims carry a ``data-requires``
attribute and start with the CSS class ``nav-hidden`` so the client-side JS
can selectively reveal them after fetching the user's profile.

These tests verify:
  - The HTML contract (``data-requires`` + ``nav-hidden``) is present and
    correct in server-rendered pages.
  - Unauthenticated visitors see only public links by default.
  - Authenticated users see auth-gated links when the page loads.
  - The ``/admin`` page is protected and only reachable with admin claims.
"""

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

import httpx
import pytest

from helpers import oidc_register_session, complete_registration, activate_account, oidc_login


# ---------------------------------------------------------------------------
# HTML parser that extracts <a> tags inside #sidebar-nav
# ---------------------------------------------------------------------------


class _NavLink:
    """Represents a parsed ``<a>`` tag from the sidebar nav."""

    __slots__ = ("href", "data_requires", "classes", "id", "text")

    def __init__(
        self,
        href: str,
        data_requires: Optional[str],
        classes: List[str],
        id: Optional[str],
        text: str,
    ) -> None:
        self.href = href
        self.data_requires = data_requires
        self.classes = classes
        self.id = id
        self.text = text

    def __repr__(self) -> str:
        return (
            f"NavLink(href={self.href!r}, requires={self.data_requires!r}, "
            f"classes={self.classes!r}, text={self.text!r})"
        )


class _SidebarNavParser(HTMLParser):
    """Extract ``<a>`` tags from the ``<nav id="sidebar-nav">`` element."""

    def __init__(self) -> None:
        super().__init__()
        self._in_nav = False
        self._nav_depth = 0
        self._current_tag: Optional[str] = None
        self._current_attrs: Dict[str, Optional[str]] = {}
        self._current_text = ""
        self.links: List[_NavLink] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_dict = dict(attrs)
        if tag == "nav" and attr_dict.get("id") == "sidebar-nav":
            self._in_nav = True
            self._nav_depth = 1
            return
        if self._in_nav:
            self._nav_depth += 1
            if tag == "a":
                self._current_tag = "a"
                self._current_attrs = attr_dict
                self._current_text = ""

    def handle_endtag(self, tag: str) -> None:
        if self._in_nav:
            if tag == "a" and self._current_tag == "a":
                self.links.append(
                    _NavLink(
                        href=self._current_attrs.get("href", ""),
                        data_requires=self._current_attrs.get("data-requires"),
                        classes=(self._current_attrs.get("class") or "").split(),
                        id=self._current_attrs.get("id"),
                        text=self._current_text.strip(),
                    )
                )
                self._current_tag = None
            self._nav_depth -= 1
            if self._nav_depth <= 0:
                self._in_nav = False

    def handle_data(self, data: str) -> None:
        if self._current_tag == "a":
            self._current_text += data


def _parse_nav(html: str) -> List[_NavLink]:
    """Parse *html* and return the list of sidebar nav links."""
    parser = _SidebarNavParser()
    parser.feed(html)
    return parser.links


# ---------------------------------------------------------------------------
# Aliases — reuse shared OIDC helpers
# ---------------------------------------------------------------------------

_oidc_login_session = oidc_register_session
_complete_registration = complete_registration


# ---------------------------------------------------------------------------
# Expected nav link contract
# ---------------------------------------------------------------------------

# (href, data_requires, should_have_nav_hidden)
EXPECTED_NAV_LINKS = [
    ("/happyhour", None, False),               # public
    ("/mealbot", "MEALBOT", True),
    ("/admin", "ADMIN", True),
    ("/account", "auth", True),
    ("/login", "guest", False),                # visible by default for guests
    ("#", "auth", True),                       # logout link
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNavHtmlContract:
    """Verify the server-rendered HTML carries the correct nav link attributes.

    These tests do NOT execute JavaScript — they verify the HTML contract that
    the client-side ``updateNavVisibility()`` function relies on.
    """

    def test_nav_links_present(
        self, frontend_client: httpx.Client
    ) -> None:
        """All expected nav links appear in the rendered page."""
        # /login is public, so no auth needed
        resp = frontend_client.get("/login")
        assert resp.status_code == 200
        links = _parse_nav(resp.text)

        found_hrefs = [l.href for l in links]
        for href, _, _ in EXPECTED_NAV_LINKS:
            assert href in found_hrefs, (
                f"Expected nav link {href!r} not found. Got: {found_hrefs}"
            )

    def test_data_requires_attributes(
        self, frontend_client: httpx.Client
    ) -> None:
        """Each nav link has the correct ``data-requires`` value (or none)."""
        resp = frontend_client.get("/login")
        assert resp.status_code == 200
        links = _parse_nav(resp.text)

        link_map = {l.href: l for l in links}

        for href, expected_requires, _ in EXPECTED_NAV_LINKS:
            link = link_map[href]
            assert link.data_requires == expected_requires, (
                f"Link {href}: expected data-requires={expected_requires!r}, "
                f"got {link.data_requires!r}"
            )

    def test_nav_hidden_classes(
        self, frontend_client: httpx.Client
    ) -> None:
        """Gated links have ``nav-hidden`` in their class list by default."""
        resp = frontend_client.get("/login")
        assert resp.status_code == 200
        links = _parse_nav(resp.text)

        link_map = {l.href: l for l in links}

        for href, _, should_be_hidden in EXPECTED_NAV_LINKS:
            link = link_map[href]
            has_hidden = "nav-hidden" in link.classes
            assert has_hidden == should_be_hidden, (
                f"Link {href}: nav-hidden expected={should_be_hidden}, "
                f"actual={has_hidden} (classes={link.classes})"
            )

    def test_nav_hidden_css_rule_exists(
        self, frontend_client: httpx.Client
    ) -> None:
        """The ``nav-hidden`` CSS rule is present in main.css."""
        resp = frontend_client.get("/static/css/main.css")
        assert resp.status_code == 200
        assert "nav-hidden" in resp.text
        # Verify the rule actually hides elements
        assert "display" in resp.text.lower() and "none" in resp.text.lower()

    def test_nav_consistent_across_pages(
        self, frontend_client: httpx.Client
    ) -> None:
        """The nav link contract is identical on all public pages."""
        public_pages = ["/login", "/happyhour"]
        reference_links = None

        for page in public_pages:
            resp = frontend_client.get(page)
            assert resp.status_code == 200, f"{page} returned {resp.status_code}"
            links = _parse_nav(resp.text)
            signature = [
                (l.href, l.data_requires, "nav-hidden" in l.classes)
                for l in links
            ]
            if reference_links is None:
                reference_links = signature
            else:
                assert signature == reference_links, (
                    f"Nav on {page} differs from /login:\n"
                    f"  /login:  {reference_links}\n"
                    f"  {page}: {signature}"
                )


class TestNavProtectedPageAccess:
    """Verify server-side enforcement that backs up the client-side nav filtering."""

    def test_admin_page_requires_auth(
        self, frontend_client: httpx.Client
    ) -> None:
        """Unauthenticated request to /admin redirects to /login."""
        resp = frontend_client.get("/admin")
        assert resp.status_code == 302
        assert resp.headers["location"].endswith("/login")

    def test_admin_api_requires_admin_claim(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """A regular (non-admin) user gets 403 on admin API endpoints."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _oidc_login_session(
            backend_url, oidc_issuer,
            sub="nav-test-nonadmin", name="Nav NonAdmin", email="nav-nonadmin@test.local",
        )
        _complete_registration(client, "nav_nonadmin_user")
        client.close()

        # Activate so the 403 comes from the claims check, not the status check
        activate_account(backend_db_path, "nav_nonadmin_user")

        client = oidc_login(
            backend_url, oidc_issuer,
            sub="nav-test-nonadmin", name="Nav NonAdmin", email="nav-nonadmin@test.local",
        )
        resp = client.get("/api/v2/account/admin/claims")
        assert resp.status_code == 403
        client.close()

    def test_admin_api_accessible_with_admin_claim(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """A user with ADMIN claim can access admin API endpoints."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        import sqlite3

        client = _oidc_login_session(
            backend_url, oidc_issuer,
            sub="nav-test-admin", name="Nav Admin", email="nav-admin@test.local",
        )
        _complete_registration(client, "nav_admin_user")
        client.close()

        # Activate + grant ADMIN claim (BASIC|ADMIN = 3)
        conn = sqlite3.connect(backend_db_path)
        try:
            conn.execute(
                "UPDATE accounts SET status = 'active', claims = 3 WHERE username = ?",
                ("nav_admin_user",),
            )
            conn.commit()
        finally:
            conn.close()

        client = oidc_login(
            backend_url, oidc_issuer,
            sub="nav-test-admin", name="Nav Admin", email="nav-admin@test.local",
        )
        resp = client.get("/api/v2/account/admin/claims")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        client.close()


class TestNavAuthenticatedHtml:
    """Verify the nav HTML for authenticated users still carries the right attributes.

    Even for authenticated sessions, the server-rendered HTML is identical — the
    JS client reveals links dynamically. Protected pages served through the
    frontend proxy should still contain the same nav structure.
    """

    def test_protected_page_nav_has_data_requires(
        self, frontend_server, backend_server, oidc_server, backend_db_path
    ) -> None:
        """An authenticated user's page still includes data-requires on nav links."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Register, activate, then re-login to get an authenticated session.
        reg_client = _oidc_login_session(
            backend_url, oidc_issuer,
            sub="nav-auth-html-user", name="Nav Auth User", email="nav-auth@test.local",
        )
        _complete_registration(reg_client, "nav_auth_html_user")
        reg_client.close()

        activate_account(backend_db_path, "nav_auth_html_user")

        backend_client = oidc_login(
            backend_url, oidc_issuer,
            sub="nav-auth-html-user", name="Nav Auth User", email="nav-auth@test.local",
        )

        # Extract the session cookie
        session_cookie = None
        for cookie in backend_client.cookies.jar:
            if "session" in cookie.name.lower():
                session_cookie = (cookie.name, cookie.value)
                break
        assert session_cookie is not None, (
            "Backend did not set a session cookie after login"
        )
        backend_client.close()

        # Set the cookie on a frontend client and fetch a protected page
        with httpx.Client(
            base_url=frontend_url, follow_redirects=False, timeout=10.0
        ) as fe_session:
            fe_session.cookies.set(session_cookie[0], session_cookie[1])

            resp = fe_session.get("/account")
            assert resp.status_code == 200

            # Verify nav links are present with correct attributes
            links = _parse_nav(resp.text)
            link_map = {l.href: l for l in links}

            # Admin link should be present with correct data-requires
            assert "/admin" in link_map, "Admin link missing from nav"
            assert link_map["/admin"].data_requires == "ADMIN"
            assert "nav-hidden" in link_map["/admin"].classes

            # Account link should be present with auth requirement
            assert "/account" in link_map, "Account link missing from nav"
            assert link_map["/account"].data_requires == "auth"
            assert "nav-hidden" in link_map["/account"].classes

            # Public link should have no data-requires
            assert "/happyhour" in link_map, "Happy Hour link missing from nav"
            assert link_map["/happyhour"].data_requires is None
            assert "nav-hidden" not in link_map["/happyhour"].classes
