"""Visual Approval Tests — Screenshot Every Workflow Stage.

Takes a screenshot at each stage of every user-facing workflow,
saving them into a timestamped directory for human review.

Run:
    pytest test_visual_approval.py -v --screenshots-dir=./screenshots

Or from the root Makefile:
    make test-visual

The test creates a numbered screenshot at every milestone so a human
can review the progression page-by-page without running the app.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

import httpx
import pytest

from helpers import (
    activate_account,
    rewrite_oidc_url,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCREENSHOT_DIR: Path | None = None
_STEP = 0


def _screenshot_dir(request) -> Path:
    """Resolve the screenshot output directory."""
    global _SCREENSHOT_DIR
    if _SCREENSHOT_DIR is None:
        d = request.config.getoption("--screenshots-dir", None)
        if d:
            _SCREENSHOT_DIR = Path(d)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            _SCREENSHOT_DIR = Path(__file__).parent / "screenshots" / ts
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SCREENSHOT_DIR


def _snap(page, name: str, request) -> Path:
    """Take a screenshot with an auto-incrementing step number."""
    global _STEP
    _STEP += 1
    d = _screenshot_dir(request)
    path = d / f"{_STEP:03d}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


# ---------------------------------------------------------------------------
# Shared OIDC login helper
# ---------------------------------------------------------------------------

def _oidc_login_cookies(
    backend_url: str,
    oidc_issuer: str,
    *,
    sub: str,
    name: str = "Test User",
    email: str = "test@test.local",
    mode: str = "login",
) -> dict[str, str]:
    """Drive an OIDC login/register flow and return session cookies.

    :param mode: "login" or "register"
    :returns: Dict of cookie name → value pairs.
    """
    client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    endpoint = f"/api/v2/auth/{mode}/test"
    resp = client.get(endpoint)
    assert resp.status_code in (302, 307), f"{endpoint} returned {resp.status_code}"
    auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
    resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
        "redirect_uri": qs["redirect_uri"][0],
        "state": qs["state"][0],
        "nonce": qs["nonce"][0],
        "sub": sub,
        "name": name,
        "email": email,
    })
    resp = httpx.get(approve, follow_redirects=False, timeout=10)
    assert resp.status_code == 302
    cb = urlparse(resp.headers["location"])
    client.get(f"{cb.path}?{cb.query}")
    cookies = dict(client.cookies.items())
    client.close()
    return cookies


def _inject_cookies(page_or_context, cookies: dict[str, str], url: str) -> None:
    """Add cookies to a Playwright page or browser context."""
    target = getattr(page_or_context, "context", page_or_context)
    for k, v in cookies.items():
        target.add_cookies([{"name": k, "value": v, "url": url}])


def _register_and_activate(
    backend_url: str,
    oidc_issuer: str,
    db_path: str,
    *,
    sub: str,
    username: str,
    name: str = "Test User",
    email: str = "test@test.local",
) -> None:
    """Register a user via OIDC, complete registration, and activate."""
    client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    resp = client.get("/api/v2/auth/register/test")
    auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
    resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
        "redirect_uri": qs["redirect_uri"][0],
        "state": qs["state"][0],
        "nonce": qs["nonce"][0],
        "sub": sub, "name": name, "email": email,
    })
    resp = httpx.get(approve, follow_redirects=False, timeout=10)
    cb = urlparse(resp.headers["location"])
    client.get(f"{cb.path}?{cb.query}")
    csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
    client.post(
        "/api/v2/auth/complete-registration",
        json={"username": username},
        headers={"X-CSRF-Token": csrf},
    )
    client.close()
    activate_account(db_path, username)


def _grant_claims_via_db(db_path: str, username: str, claims_int: int) -> None:
    """Set account claims via direct DB access."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE accounts SET claims = ? WHERE username = ?",
        (claims_int, username),
    )
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCREENSHOT_DIR: Path | None = None
_STEP = 0


def _screenshot_dir(request) -> Path:
    """Resolve the screenshot output directory."""
    global _SCREENSHOT_DIR
    if _SCREENSHOT_DIR is None:
        d = request.config.getoption("--screenshots-dir", None)
        if d:
            _SCREENSHOT_DIR = Path(d)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            _SCREENSHOT_DIR = Path(__file__).parent / "screenshots" / ts
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SCREENSHOT_DIR


def _snap(page, name: str, request) -> Path:
    """Take a screenshot with an auto-incrementing step number."""
    global _STEP
    _STEP += 1
    d = _screenshot_dir(request)
    path = d / f"{_STEP:03d}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def conftest_screenshot_option(parser):
    """Add --screenshots-dir CLI option (called from conftest.py)."""
    parser.addoption(
        "--screenshots-dir",
        action="store",
        default=None,
        help="Directory to save visual approval screenshots",
    )


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--screenshots-dir",
        action="store",
        default=None,
        help="Directory to save visual approval screenshots",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_step():
    """Reset the step counter between tests so numbering is per-test."""
    global _STEP
    _STEP = 0


# ---------------------------------------------------------------------------
# Test: Full Visual Walkthrough
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("RUN_VISUAL_TESTS"),
    reason="Set RUN_VISUAL_TESTS=1 to run visual approval tests",
)
class TestVisualApproval:
    """Walk through every user-facing workflow and capture screenshots.

    Coverage checklist:
      Pages: /, /login, /auth/complete-registration, /auth/claim-account,
             /account, /mealbot, /mealbot/individualized, /happyhour,
             /admin, 404
      Flows: registration, login, profile edit, claim toggle, theme switch,
             mealbot record, happy hour submit, admin approve/ban/defunct,
             admin claim review, defunct read-only, logout
      Viewports: desktop + mobile (with sidebar toggle)
      Themes: 13-theme showcase on /account
    """

    # ── 01  Public pages (no auth) ────────────────────────────────────

    def test_01_public_pages(self, page, frontend_server, request):
        """Screenshot all publicly accessible pages."""
        frontend_url, _ = frontend_server

        page.goto(f"{frontend_url}/")
        page.wait_for_load_state("networkidle")
        _snap(page, "index_page", request)

        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        _snap(page, "login_page", request)

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        _snap(page, "happyhour_public", request)

        page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_load_state("networkidle")
        _snap(page, "complete_registration_page", request)

        page.goto(f"{frontend_url}/auth/claim-account")
        page.wait_for_load_state("networkidle")
        _snap(page, "claim_account_page", request)

        # 404 page
        page.goto(f"{frontend_url}/nonexistent-page")
        page.wait_for_load_state("networkidle")
        _snap(page, "404_page", request)

    # ── 02  OIDC registration flow ───────────────────────────────────

    def test_02_registration_flow(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot the full browser-driven OIDC registration flow.

        Login page → click Register → Mock OIDC authorize page → fill
        form → click Authorize → complete-registration page → fill
        username → pending approval message.
        """
        frontend_url, _ = frontend_server
        frontend_port = frontend_server[1]

        # ── Step 1: Login page ──
        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        _snap(page, "oidc_01_login_page", request)

        # ── Step 2: Click "Register with Test Provider" ──
        page.wait_for_selector("#login-actions a", timeout=5000)
        register_link = page.locator("a", has_text="Register with Test Provider")
        _snap(page, "oidc_02_register_link_visible", request)
        register_link.click()

        # ── Step 3: Mock OIDC authorize page ──
        page.wait_for_selector("button[type='submit']", timeout=10000)
        _snap(page, "oidc_03_mock_oidc_authorize_page", request)

        # Fill in the identity fields
        page.fill("input[name='sub']", "vis-oidc-reg-user")
        page.fill("input[name='name']", "Visual OIDC User")
        page.fill("input[name='email']", "vis-oidc@test.local")
        _snap(page, "oidc_04_mock_oidc_form_filled", request)

        # ── Step 4: Click Authorize ──
        page.click("button[type='submit']")

        # ── Step 5: Complete Registration page ──
        # The OIDC callback lands on the backend's port; the backend redirects
        # to /auth/complete-registration.  If we landed on the backend's port
        # instead of the frontend, navigate to the frontend (cookies are
        # port-agnostic per RFC 6265).
        page.wait_for_url("**/complete-registration**", timeout=10000)
        current = page.url
        if f":{frontend_port}" not in current:
            page.goto(f"{frontend_url}/auth/complete-registration")

        page.wait_for_selector("#complete-registration-form", timeout=5000)
        _snap(page, "oidc_05_complete_registration_form", request)

        # Fill in username and submit
        page.fill("#username", "vis_oidc_user")
        _snap(page, "oidc_06_username_filled", request)
        page.click('#complete-registration-form button[type="submit"]')

        # ── Step 6: Pending approval message ──
        result = page.locator("#complete-registration-result")
        result.wait_for(state="visible", timeout=5000)
        _snap(page, "oidc_07_pending_approval_message", request)

        # ── Step 7: Activate and login via browser ──
        activate_account(backend_db_path, "vis_oidc_user")

        # Now drive the LOGIN flow through the browser
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        login_link = page.locator("a", has_text="Login with Test Provider")
        _snap(page, "oidc_08_login_link_visible", request)
        login_link.click()

        # Mock OIDC page again (login mode)
        page.wait_for_selector("button[type='submit']", timeout=10000)
        _snap(page, "oidc_09_mock_oidc_login_page", request)

        page.fill("input[name='sub']", "vis-oidc-reg-user")
        page.fill("input[name='name']", "Visual OIDC User")
        page.fill("input[name='email']", "vis-oidc@test.local")
        page.click("button[type='submit']")

        # After login callback, backend redirects to /api/v2/account/profile
        # or the configured redirect. Wait for navigation to settle.
        page.wait_for_load_state("networkidle", timeout=10000)
        time.sleep(1)
        _snap(page, "oidc_10_post_login_landing", request)

        # Navigate to account page to confirm we're authenticated
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "oidc_11_account_page_after_login", request)

    # ── 03  Account page — profile & claims ──────────────────────────

    def test_03_account_interactions(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot profile editing, claim toggles, and theme picker."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Login as dev-admin (has ALL claims)
        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "account_admin_full", request)

        # Toggle a claim off
        checkbox = page.query_selector('.claim-checkbox[data-claim="MEALBOT"]')
        if checkbox and checkbox.is_checked():
            checkbox.click()
            time.sleep(0.8)
            _snap(page, "account_mealbot_unchecked", request)
            # Toggle it back on
            checkbox.click()
            time.sleep(0.8)
            _snap(page, "account_mealbot_rechecked", request)

        # Scroll to theme picker
        picker = page.query_selector("#theme-picker")
        if picker:
            picker.scroll_into_view_if_needed()
            time.sleep(0.3)
            _snap(page, "account_theme_picker_visible", request)

    # ── 04  Mealbot page — summary + record ──────────────────────────

    def test_04_mealbot_page(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot the Mealbot dashboard and record a meal."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a second user so mealbot has someone to record against
        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="mealbot-peer", username="peer_user",
            name="Peer User", email="peer@test.local",
        )
        # Give them MEALBOT claim
        _grant_claims_via_db(backend_db_path, "peer_user", 1 | 4)  # BASIC | MEALBOT

        # Login as dev-admin
        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        # Mealbot dashboard
        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "mealbot_dashboard_empty", request)

        # Type a username into the other-person field and click "I Paid"
        other_input = page.query_selector("#other-user-input")
        if other_input:
            other_input.fill("peer_user")
            time.sleep(0.3)
            _snap(page, "mealbot_other_user_filled", request)

            i_paid = page.query_selector("#i-paid-btn")
            if i_paid:
                i_paid.click()
                time.sleep(1)
                _snap(page, "mealbot_after_i_paid", request)

        # My Summary / individualized page
        page.goto(f"{frontend_url}/mealbot/individualized")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "mealbot_individualized", request)

    # ── 05  Happy Hour authenticated view ────────────────────────────

    def test_05_happyhour_authenticated(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot Happy Hour page with tyrant management sections."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Login as dev-admin (has HAPPY_HOUR_TYRANT)
        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "happyhour_authenticated", request)

        # Scroll to the submit section if present
        submit_section = page.query_selector("#happyhour-submit-section")
        if submit_section:
            submit_section.scroll_into_view_if_needed()
            time.sleep(0.5)
            _snap(page, "happyhour_submit_section", request)

        # Scroll to locations section if present
        loc_section = page.query_selector("#happyhour-locations-section")
        if loc_section:
            loc_section.scroll_into_view_if_needed()
            time.sleep(0.5)
            _snap(page, "happyhour_locations_section", request)

        # Show "Add New Location" fields
        loc_select = page.query_selector("#location-select")
        if loc_select:
            loc_select.select_option("new")
            time.sleep(0.5)
            _snap(page, "happyhour_new_location_form", request)

    # ── 06  Admin dashboard — all tabs + actions ─────────────────────

    def test_06_admin_dashboard(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot every admin tab, plus approve/status-change actions."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a pending user for admin to see
        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="pending-vis", username="pending_vis",
            name="Pending Visible", email="pendvis@test.local",
        )
        # Re-set to pending_approval so admin sees them
        conn = sqlite3.connect(backend_db_path)
        conn.execute(
            "UPDATE accounts SET status = 'pending_approval' "
            "WHERE username = 'pending_vis'"
        )
        conn.commit()
        conn.close()

        # Login as admin
        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "admin_pending_tab", request)

        # Approve the pending account
        approve_btn = page.query_selector(".approve-account-btn")
        if approve_btn:
            approve_btn.click()
            time.sleep(1)
            _snap(page, "admin_after_approve", request)

        # All Accounts tab
        tabs = page.query_selector_all(".admin-tab")
        if len(tabs) > 1:
            tabs[1].click()
            time.sleep(1)
            _snap(page, "admin_all_accounts_tab", request)

            # Use status filter
            filt = page.query_selector("#admin-status-filter")
            if filt:
                filt.select_option("active")
                time.sleep(1)
                _snap(page, "admin_filter_active", request)
                filt.select_option("")
                time.sleep(0.5)

        # Claim Requests tab
        if len(tabs) > 2:
            tabs[2].click()
            time.sleep(1)
            _snap(page, "admin_claims_tab", request)

    # ── 07  Defunct (disabled) account — read-only ────────────────────

    def test_07_defunct_account(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot what a defunct account sees — banner + disabled controls."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        sub = "defunct-vis-user"
        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub=sub, username="defunctvis",
            name="Defunct Vis", email="defunctvis@test.local",
        )
        # Give them MEALBOT+HAPPY_HOUR before marking defunct
        _grant_claims_via_db(backend_db_path, "defunctvis", 1 | 4 | 16)
        conn = sqlite3.connect(backend_db_path)
        conn.execute(
            "UPDATE accounts SET status = 'defunct' WHERE username = 'defunctvis'"
        )
        conn.commit()
        conn.close()

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub=sub, name="Defunct Vis", email="defunctvis@test.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        # Account page — should show defunct banner + disabled controls
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "defunct_account_page", request)

        # Mealbot page — should load but record buttons won't work
        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "defunct_mealbot_page", request)

        # Happy Hour page — should show data but submit is blocked
        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "defunct_happyhour_page", request)

    # ── 08  Theme showcase ───────────────────────────────────────────

    def test_08_theme_showcase(
        self, page, frontend_server, backend_server, oidc_server, request,
    ):
        """Screenshot all 23 themes on the account page."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        all_themes = [
            "default", "light", "solarized-dark", "solarized-light",
            "nord", "dracula", "monokai", "cyberpunk", "ocean", "forest",
            "sunset", "midnight-purple", "cherry-blossom", "retro-terminal",
            "high-contrast", "warm-earth", "arctic", "neon", "paper",
            "slate", "rose-gold", "emerald", "coffee",
        ]

        for theme in all_themes:
            page.goto(f"{frontend_url}/account")
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)
            if theme == "default":
                page.evaluate(
                    "document.documentElement.removeAttribute('data-theme')"
                )
            else:
                page.evaluate(
                    f"document.documentElement.setAttribute('data-theme', '{theme}')"
                )
            time.sleep(0.3)
            _snap(page, f"theme_{theme}", request)

    # ── 09  Mobile views (all pages + sidebar) ───────────────────────

    def test_09_mobile_views(
        self, browser, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot every page at mobile viewport width."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        context = browser.new_context(
            base_url=frontend_url,
            viewport={"width": 375, "height": 812},
            is_mobile=True,
        )
        mob_page = context.new_page()

        # Login as admin
        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(context, cookies, frontend_url)

        pages_to_shot = [
            ("/", "mobile_index"),
            ("/login", "mobile_login"),
            ("/account", "mobile_account"),
            ("/admin", "mobile_admin"),
            ("/happyhour", "mobile_happyhour"),
            ("/mealbot", "mobile_mealbot"),
            ("/mealbot/individualized", "mobile_my_summary"),
            ("/auth/complete-registration", "mobile_registration"),
        ]

        for path, snap_name in pages_to_shot:
            mob_page.goto(f"{frontend_url}{path}")
            mob_page.wait_for_load_state("networkidle")
            time.sleep(1)
            _snap(mob_page, snap_name, request)

            # Open sidebar on mobile
            toggle = mob_page.query_selector("#menu-toggle")
            if toggle and toggle.is_visible():
                toggle.click()
                time.sleep(0.5)
                _snap(mob_page, f"{snap_name}_sidebar_open", request)
                overlay = mob_page.query_selector("#sidebar-overlay")
                if overlay and overlay.is_visible():
                    overlay.click()
                    time.sleep(0.3)

        mob_page.close()
        context.close()

    # ── 10  Error page & login redirect ──────────────────────────────

    def test_10_error_and_redirect(
        self, page, frontend_server, request,
    ):
        """Screenshot the login error state and auth-gated redirect."""
        frontend_url, _ = frontend_server

        # Login page with error query param
        page.goto(f"{frontend_url}/login?error=Your+account+is+banned.")
        page.wait_for_load_state("networkidle")
        _snap(page, "login_error_message", request)

        # Trying to access /account without auth → redirect to /login
        page.context.clear_cookies()
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        _snap(page, "login_redirect_from_account", request)

    # ── 11  OIDC login for banned / defunct user via browser ─────────

    def test_11_oidc_rejected_login(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot what happens when a banned user tries to login via OIDC.

        Full browser flow: login page → OIDC → callback → redirect back
        to /login?error=... with the error banner visible.
        """
        frontend_url, _ = frontend_server
        frontend_port = frontend_server[1]
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a banned user
        sub = "banned-oidc-user"
        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub=sub, username="banned_oidc",
            name="Banned OIDC", email="banned-oidc@test.local",
        )
        conn = sqlite3.connect(backend_db_path)
        conn.execute(
            "UPDATE accounts SET status = 'banned' "
            "WHERE username = 'banned_oidc'"
        )
        conn.commit()
        conn.close()

        # Clear cookies from prior tests
        page.context.clear_cookies()

        # ── Drive the login flow through the browser ──
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        _snap(page, "banned_01_login_page", request)

        page.locator("a", has_text="Login with Test Provider").click()
        page.wait_for_selector("button[type='submit']", timeout=10000)
        _snap(page, "banned_02_oidc_authorize", request)

        page.fill("input[name='sub']", sub)
        page.fill("input[name='name']", "Banned OIDC")
        page.fill("input[name='email']", "banned-oidc@test.local")
        page.click("button[type='submit']")

        # The backend redirects to /login?error=Your+account+is+banned.
        page.wait_for_url("**/login**", timeout=10000)

        # If we landed on the backend's port, navigate to the frontend
        current = page.url
        if f":{frontend_port}" not in current:
            from urllib.parse import urlparse as _up, parse_qs as _pq
            _parsed = _up(current)
            _qs = _pq(_parsed.query)
            error_msg = _qs.get("error", [""])[0]
            if error_msg:
                page.goto(
                    f"{frontend_url}/login?error={error_msg}"
                )
            else:
                page.goto(f"{frontend_url}/login")

        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        _snap(page, "banned_03_login_error_after_oidc", request)

    # ── 12  Claim existing account flow via browser ──────────────────

    def test_12_claim_account_flow(
        self, page, frontend_server, backend_server, oidc_server,
        backend_db_path, request,
    ):
        """Screenshot the claim-account flow from registration page.

        A new OIDC user sees the claim section on complete-registration
        when legacy accounts exist, fills in the claim form, and sees
        the submission confirmation.
        """
        frontend_url, _ = frontend_server
        frontend_port = frontend_server[1]

        # First, create a legacy account that can be claimed
        # (account with no external_unique_id matching, created via DB)
        conn = sqlite3.connect(backend_db_path)
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(username, email, phone_provider, account_provider, "
            " external_unique_id, claims, status) "
            "VALUES ('legacy_claimable', NULL, 1, 1, 'legacy-no-match', 1, 'active')"
        )
        conn.commit()
        conn.close()

        # Clear cookies
        page.context.clear_cookies()

        # Drive OIDC register flow
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        page.locator("a", has_text="Register with Test Provider").click()

        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", "claim-flow-user")
        page.fill("input[name='name']", "Claim Flow User")
        page.fill("input[name='email']", "claim-flow@test.local")
        page.click("button[type='submit']")

        page.wait_for_url("**/complete-registration**", timeout=10000)
        current = page.url
        if f":{frontend_port}" not in current:
            page.goto(f"{frontend_url}/auth/complete-registration")

        page.wait_for_selector("#complete-registration-form", timeout=5000)
        time.sleep(1.5)  # Wait for claim section to load dynamically
        _snap(page, "claim_01_registration_with_claim_section", request)

        # Check if the claim section appeared
        claim_form = page.query_selector("#claim-account-form")
        if claim_form:
            page.fill("#claim-username", "legacy_claimable")
            _snap(page, "claim_02_claim_form_filled", request)
            page.click('#claim-account-form button[type="submit"]')
            time.sleep(1)
            _snap(page, "claim_03_claim_submitted", request)
        else:
            # Claim section may not appear if no claimable accounts found
            _snap(page, "claim_02_no_claimable_accounts", request)
