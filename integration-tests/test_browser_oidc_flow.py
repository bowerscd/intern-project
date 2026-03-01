"""Browser-based end-to-end OIDC registration flow.

Drives the complete user journey through a real browser:
  Login page → "Register with Test Provider" → Mock OIDC form → Approve
  → Complete Registration page → fill username → Account page.

Requires Playwright::

    pip install playwright
    playwright install --with-deps chromium
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.browser


class TestBrowserRegistrationFlow:
    """Full OIDC registration driven through a real Chromium browser."""

    def test_register_via_test_provider(
        self, page, frontend_server, backend_server, oidc_server
    ) -> None:
        """Complete OIDC registration through the browser UI.

        1. Navigate to /login
        2. Click "Register with Test Provider"
        3. Fill in the Mock OIDC form and click Authorize
        4. Fill in a username on the complete-registration page
        5. Verify redirect to /account
        """
        oidc_issuer, _ = oidc_server

        # ── Step 1: Load the login page ──
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        # The test provider links only appear in dev mode.
        # Wait for JS to render the login actions.
        page.wait_for_selector("#login-actions a", timeout=5000)

        # ── Step 2: Click "Register with Test Provider" ──
        register_link = page.locator("a", has_text="Register with Test Provider")
        assert register_link.is_visible(), (
            "Register with Test Provider link not found — is DEV mode enabled?"
        )
        register_link.click()

        # ── Step 3: Mock OIDC authorize page ──
        # The browser follows the redirect chain:
        #   frontend → backend /api/v2/auth/register/test → OIDC /authorize
        page.wait_for_selector("button[type='submit']", timeout=10000)
        assert "Mock OIDC" in page.content()

        # Fill in a unique sub/name/email so this test doesn't collide
        page.fill("input[name='sub']", "browser-e2e-user")
        page.fill("input[name='name']", "Browser E2E User")
        page.fill("input[name='email']", "browser-e2e@test.local")

        page.click("button[type='submit']")

        # ── Step 4: Complete Registration page ──
        # After the OIDC callback the backend redirects to /auth/complete-registration
        # on its own port (the redirect_uri in the test config points at the backend
        # directly).  Navigate to the *frontend's* complete-registration page — the
        # session cookie carries over because cookies are port-agnostic (RFC 6265).
        page.wait_for_url("**/complete-registration**", timeout=10000)
        frontend_url, _ = frontend_server
        page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)

        page.fill("#username", "browser_e2e_user")
        page.click('#complete-registration-form button[type="submit"]')

        # ── Step 5: Verify success and redirect to /account ──
        page.wait_for_url("**/account**", timeout=10000)
        assert "/account" in page.url

    def test_duplicate_registration_shows_error(
        self, page, browser_context, frontend_server, backend_server, oidc_server
    ) -> None:
        """Registering with a taken username should show an error in the browser.

        This test uses a fresh context so it doesn't share cookies with the
        test above, but it *does* reuse the same backend (session-scoped)
        so the username from the previous test is already taken.
        """
        oidc_issuer, _ = oidc_server

        # Register first user to guarantee the username is taken
        self._register_through_browser(
            page, oidc_issuer, frontend_server,
            sub="dup-check-first",
            name="First User",
            email="first@test.local",
            username="dup_check_user",
        )

        # Open a fresh page (new context) for the second registration
        new_page = browser_context.new_page()
        try:
            self._register_through_browser(
                new_page, oidc_issuer, frontend_server,
                sub="dup-check-second",
                name="Second User",
                email="second@test.local",
                username="dup_check_user",
                expect_success=False,
            )

            # The page should show an error message
            result = new_page.locator("#complete-registration-result")
            result.wait_for(state="visible", timeout=5000)
            assert "error" in result.inner_text().lower() or "409" in result.inner_text()
        finally:
            new_page.close()

    # ── Helpers ──

    @staticmethod
    def _register_through_browser(
        page,
        oidc_issuer: str,
        frontend_server: tuple,
        *,
        sub: str,
        name: str,
        email: str,
        username: str,
        expect_success: bool = True,
    ) -> None:
        """Drive the OIDC registration flow in the browser.

        Shared logic extracted so multiple tests can reuse it.
        """
        frontend_url, frontend_port = frontend_server

        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        page.locator("a", has_text="Register with Test Provider").click()

        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", sub)
        page.fill("input[name='name']", name)
        page.fill("input[name='email']", email)
        page.click("button[type='submit']")

        page.wait_for_url("**/complete-registration**", timeout=10000)

        # The OIDC callback lands on the backend's port; bounce to the frontend
        # where the HTML form lives.  The session cookie is port-agnostic.
        current = page.url
        if f":{frontend_port}" not in current:
            page.goto(f"{frontend_url}/auth/complete-registration")

        page.wait_for_selector("#complete-registration-form", timeout=5000)
        page.fill("#username", username)
        page.click('#complete-registration-form button[type="submit"]')

        if expect_success:
            page.wait_for_url("**/account**", timeout=10000)
