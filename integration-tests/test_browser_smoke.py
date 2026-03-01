"""Browser-based smoke tests using Playwright.

These tests launch a real browser against the live frontend + backend stack
and verify that pages load, render expected content, and navigation works.

Requires Playwright to be installed::

    pip install playwright
    playwright install --with-deps chromium

Run only browser tests::

    pytest -m browser -v

Skip browser tests::

    pytest -m 'not browser' -v
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.browser


class TestPublicPages:
    """Public pages should load and render expected content in a real browser."""

    def test_login_page_renders(self, page, frontend_server) -> None:
        """The login page should display OIDC provider links."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        assert "Vibe Coded" in page.title()
        heading = page.locator("h2")
        assert heading.first.is_visible()

    def test_happy_hour_page_accessible(self, page, frontend_server) -> None:
        """The public happy hour page should load without authentication."""
        page.goto("/happyhour")
        page.wait_for_load_state("domcontentloaded")

        assert page.url.endswith("/happyhour")

    def test_static_css_loads(self, page, frontend_server) -> None:
        """CSS should be served and applied (basic resource loading check)."""
        page.goto("/login")
        page.wait_for_load_state("networkidle")

        # Verify that the main stylesheet was loaded
        stylesheets = page.evaluate(
            "() => Array.from(document.styleSheets).map(s => s.href).filter(Boolean)"
        )
        css_loaded = any("main.css" in href for href in stylesheets)
        assert css_loaded, f"main.css not found in loaded stylesheets: {stylesheets}"


class TestUnauthenticatedRedirects:
    """Protected pages should redirect to /login when visited without a session."""

    @pytest.mark.parametrize("path", ["/", "/account", "/mealbot", "/admin"])
    def test_protected_page_redirects_to_login(self, page, frontend_server, path) -> None:
        """Visiting a protected page should redirect to the login page."""
        page.goto(path)
        page.wait_for_url("**/login**", timeout=5000)

        assert "/login" in page.url


class TestNavSidebar:
    """The sidebar navigation should be present and interactive."""

    def test_sidebar_has_links(self, page, frontend_server) -> None:
        """The sidebar should contain navigation links."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        sidebar = page.locator("#sidebar")
        assert sidebar.is_visible()

        nav_links = sidebar.locator("a")
        assert nav_links.count() > 0

    def test_brand_link_present(self, page, frontend_server) -> None:
        """The brand link should be visible in the sidebar."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        brand = page.locator(".brand")
        assert brand.is_visible()
        assert brand.inner_text().strip() == "Vibe Coded"
