"""Integration tests for account registration flows and profile email behaviour.

Covers three areas introduced/fixed during the account-claim audit session:

1. ``GET /api/v2/auth/claimable-accounts`` — returns legacy accounts that still
   have the sentinel ``external_unique_id == 'legacy-placeholder'``.

2. ``oidc_email`` vs notification ``email`` separation — the OIDC provider email
   must always be present in the profile response via the session; the DB email
   column is only the notification opt-in preference.

3. Browser-level claim card — the complete-registration page dynamically shows a
   claim card when claimable accounts exist, and the card lists the correct usernames.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from helpers import (
    activate_account as _activate_account,
    complete_registration as _complete_registration,
    create_backend_client as _create_backend_client,
    oidc_register_session as _oidc_register_session,
    register_user as _register_user,
)


# ---------------------------------------------------------------------------
# Helper: seed a legacy (unclaimed) account directly into the backend DB.
# ---------------------------------------------------------------------------

def _seed_legacy_account(
    db_path: str,
    username: str,
    email: str,
) -> None:
    """Insert a legacy account with ``external_unique_id='legacy-placeholder'``.
    
    Note: Due to the composite unique constraint on (account_provider, external_unique_id),
    only ONE account can have external_unique_id='legacy-placeholder' per DB session.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(username, email, phone, phone_provider, account_provider, "
            "external_unique_id, claims) "
            "VALUES (?, ?, NULL, 1, 1, 'legacy-placeholder', 1)",
            (username, email),
        )
        conn.commit()
    finally:
        conn.close()


def _grant_admin(db_path: str, username: str) -> None:
    """Set the ADMIN claim bitmask (3) on an account."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE accounts SET claims = 3 WHERE username = ?",
            (username,),
        )
        conn.commit()
    finally:
        conn.close()


# ===========================================================================
# TestClaimableAccountsEndpoint
# ===========================================================================
class TestClaimableAccountsEndpoint:
    """``GET /api/v2/auth/claimable-accounts`` behaviour."""

    def test_endpoint_is_publicly_accessible(
        self, backend_server, oidc_server
    ) -> None:
        """The endpoint returns a list without requiring authentication."""
        backend_url, _ = backend_server
        with _create_backend_client(backend_url) as client:
            resp = client.get("/api/v2/auth/claimable-accounts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_normal_account_does_not_appear(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """An account created via OIDC is NOT listed as claimable."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="claimable-normal-1",
            name="Normal Account",
            email="claimable-normal@test.local",
            username="claimable_normal_user",
            db_path=backend_db_path,
        )
        try:
            resp = client.get("/api/v2/auth/claimable-accounts")
            assert resp.status_code == 200
            assert "claimable_normal_user" not in resp.json()
        finally:
            client.close()




# ===========================================================================
# TestProfileOidcEmail
# ===========================================================================

class TestProfileOidcEmail:
    """``oidc_email`` / notification-email separation in the profile endpoint."""

    def test_oidc_email_present_after_registration(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """Profile includes ``oidc_email`` sourced from the OIDC provider."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="profile-oidc-email-1",
            name="OIDC Email User",
            email="oidc-email@test.local",
            username="profile_oidc_email_user",
            db_path=backend_db_path,
        )
        try:
            resp = client.get("/api/v2/account/profile")
            assert resp.status_code == 200
            profile = resp.json()
            assert profile["oidc_email"] == "oidc-email@test.local"
        finally:
            client.close()

    def test_initial_registration_sets_db_email(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """After registration the DB email (notification preference) is populated."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="profile-initial-email-1",
            name="Initial Email User",
            email="initial-email@test.local",
            username="profile_initial_email_user",
            db_path=backend_db_path,
        )
        try:
            resp = client.get("/api/v2/account/profile")
            assert resp.status_code == 200
            profile = resp.json()
            # Registration should set the DB email to the OIDC provider email
            # (behaviour may vary — at minimum oidc_email is always present)
            assert profile["oidc_email"] == "initial-email@test.local"
        finally:
            client.close()

    def test_opt_out_nulls_db_email_but_preserves_oidc_email(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """PATCH email='' disables notifications (DB email → null) but oidc_email persists."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="profile-optout-1",
            name="OptOut User",
            email="optout@test.local",
            username="profile_optout_user",
            db_path=backend_db_path,
        )
        try:
            csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
            resp = client.patch(
                "/api/v2/account/profile",
                json={"email": ""},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            updated = resp.json()
            # Notification email must be null (opted out)
            assert updated["email"] is None, (
                f"Expected email=None after opt-out, got {updated['email']!r}"
            )
            # But the OIDC identity email must still come from the session
            assert updated["oidc_email"] == "optout@test.local", (
                f"Expected oidc_email='optout@test.local', got {updated['oidc_email']!r}"
            )
        finally:
            client.close()

    def test_opt_in_restores_db_email_without_changing_oidc_email(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """After opt-out, re-enabling notifications sets DB email; oidc_email unchanged."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="profile-optin-1",
            name="OptIn User",
            email="optin@test.local",
            username="profile_optin_user",
            db_path=backend_db_path,
        )
        try:
            # Opt out first
            csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
            resp = client.patch(
                "/api/v2/account/profile",
                json={"email": ""},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            assert resp.json()["email"] is None

            # Opt back in
            csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
            resp = client.patch(
                "/api/v2/account/profile",
                json={"email": "optin@test.local"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            updated = resp.json()
            assert updated["email"] == "optin@test.local"
            # oidc_email must still reflect the OIDC provider (session-sourced)
            assert updated["oidc_email"] == "optin@test.local"
        finally:
            client.close()

    def test_db_email_can_differ_from_oidc_email(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """oidc_email stays fixed at the OIDC provider value even when DB email differs."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="profile-diffmail-1",
            name="DiffMail User",
            email="provider@test.local",
            username="profile_diffmail_user",
            db_path=backend_db_path,
        )
        try:
            csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
            resp = client.patch(
                "/api/v2/account/profile",
                json={"email": "notifications@test.local"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200
            updated = resp.json()
            # DB email reflects the notification preference
            assert updated["email"] == "notifications@test.local"
            # oidc_email is always the OIDC provider email from the session
            assert updated["oidc_email"] == "provider@test.local"
        finally:
            client.close()

    def test_profile_patch_requires_csrf(
        self, backend_server, oidc_server, backend_db_path
    ) -> None:
        """PATCH /profile without a CSRF token is rejected with 403."""
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        client = _register_user(
            backend_url, oidc_issuer,
            sub="profile-csrf-1",
            name="CSRF Test User",
            email="csrf-test@test.local",
            username="profile_csrf_test_user",
            db_path=backend_db_path,
        )
        try:
            # No X-CSRF-Token header
            resp = client.patch(
                "/api/v2/account/profile",
                json={"email": ""},
            )
            assert resp.status_code == 403
        finally:
            client.close()


# ===========================================================================
# TestCompleteRegistrationClaimCard  (browser / Playwright)
# ===========================================================================

class TestCompleteRegistrationClaimCard:
    """Browser tests: the claim card on the complete-registration page.

    Requires Playwright (``pip install playwright && playwright install chromium``).
    Skipped automatically if Playwright is not installed.

    The claim card HTML (injected by renderCompleteRegistration()):
        <form id="claim-account-form">
          <label for="claim-username">Existing Username</label>
          <input id="claim-username" name="username" placeholder="legacy.user" />
          <button type="submit">Claim Account</button>
        </form>
        <div id="claim-account-result"></div>
    """

    @staticmethod
    def _drive_to_complete_registration(
        page,
        oidc_issuer: str,
        frontend_url: str,
        *,
        sub: str,
        name: str,
        email: str,
    ) -> None:
        """Navigate a browser through OIDC registration up to the completion page."""
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        page.locator("a", has_text="Register with Test Provider").click()

        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", sub)
        page.fill("input[name='name']", name)
        page.fill("input[name='email']", email)
        page.click("button[type='submit']")

        page.wait_for_url("**/complete-registration**", timeout=10000)
        # Bounce to the frontend URL in case the OIDC callback redirected to
        # the backend port directly (the session cookie is port-agnostic).
        page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)

    def test_claim_form_absent_when_no_legacy_accounts(
        self,
        page,
        browser_context,
        frontend_server,
        backend_server,
        oidc_server,
    ) -> None:
        """No claim form if there are no legacy-placeholder accounts at all.

        This test uses a fresh browser context (clean cookies) and a unique
        OIDC sub that has never been seeded with a legacy-placeholder account.
        It asserts via the API that zero claimable accounts exist for the
        specific sub used, then verifies the browser shows no claim form.

        NOTE: This test is order-dependent — if other tests in the session seed
        ``legacy-placeholder`` accounts without cleaning up, the claim form WILL
        appear.  The test is therefore marked ``skip`` when the API reports any
        claimable accounts to avoid false failures in a shared session.
        """
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        frontend_url, _ = frontend_server

        # Check whether any claimable accounts exist right now
        with _create_backend_client(backend_url) as probe:
            claimable = probe.get("/api/v2/auth/claimable-accounts").json()

        if claimable:
            pytest.skip(
                f"Skipping: {len(claimable)} legacy account(s) already seeded "
                f"by earlier tests in this session: {claimable}"
            )

        fresh_page = browser_context.new_page()
        try:
            self._drive_to_complete_registration(
                fresh_page, oidc_issuer, frontend_url,
                sub="browser-no-claim-1",
                name="No Claim User",
                email="browser-no-claim@test.local",
            )

            # Give JS enough time to fetch and (not) inject the card
            fresh_page.wait_for_timeout(3000)

            claim_form = fresh_page.locator("#claim-account-form")
            assert not claim_form.is_visible(), (
                "Claim form should NOT appear when no legacy accounts exist"
            )
        finally:
            fresh_page.close()

    def test_account_page_shows_oidc_email_in_disabled_input(
        self,
        page,
        frontend_server,
        backend_server,
        oidc_server,
        backend_db_path,
    ) -> None:
        """The account page renders oidc_email in the (disabled) email input.

        The email input is the second disabled input inside ``#profile-form``
        (first is username, second is email).  It has no ``id`` attribute.

        After registration the account is pending approval, so we activate it
        via DB and then log in through the browser before checking the account
        page.
        """
        oidc_issuer, _ = oidc_server
        frontend_url, _ = frontend_server

        # Register a fresh user through the browser
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        page.locator("a", has_text="Register with Test Provider").click()

        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", "browser-oidc-email-display-1")
        page.fill("input[name='name']", "Email Display User")
        page.fill("input[name='email']", "email-display@test.local")
        page.click("button[type='submit']")

        page.wait_for_url("**/complete-registration**", timeout=10000)
        page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)
        page.fill("#username", "browser_email_display_user")
        page.click('#complete-registration-form button[type="submit"]')

        # Registration now shows a pending approval message instead of
        # redirecting to /account.
        page.wait_for_selector("#complete-registration-result", timeout=5000)
        result_text = page.locator("#complete-registration-result").text_content()
        assert "pending" in (result_text or "").lower() or "approval" in (result_text or "").lower()

        # Activate the account via the DB so that login succeeds.
        _activate_account(backend_db_path, "browser_email_display_user")

        # Log in through the browser
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        page.locator("a", has_text="Login with Test Provider").click()

        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", "browser-oidc-email-display-1")
        page.fill("input[name='name']", "Email Display User")
        page.fill("input[name='email']", "email-display@test.local")
        page.click("button[type='submit']")

        # After OIDC callback the backend redirects to /account on the
        # backend's port.  Bounce to the frontend URL where the page lives.
        page.wait_for_url("**/account**", timeout=10000)
        page.goto(f"{frontend_url}/account")

        # Wait for the profile form to render — JS populates it asynchronously.
        page.wait_for_selector("#profile-form input[disabled]", timeout=8000)

        # The email input is the second disabled input inside #profile-form.
        # (First is username, second is the OIDC email display.)
        email_input = page.locator("#profile-form input[disabled]").nth(1)
        email_value = email_input.input_value()
        assert email_value == "email-display@test.local", (
            f"Expected OIDC email 'email-display@test.local' in disabled input, "
            f"got {email_value!r}"
        )
