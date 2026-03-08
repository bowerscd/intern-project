"""Visual Approval Tests — Screenshot Every Workflow Stage.

Each test resets the database and seeds its own data, so tests are
fully isolated and can run in any order.

Run:
    RUN_VISUAL_TESTS=1 pytest test_visual_approval.py -v

The test creates a numbered screenshot at every milestone so a human
can review the progression page-by-page without running the app.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

import httpx
import pytest

from helpers import (
    activate_account,
    rewrite_oidc_url,
)

# ── Claim bitmask constants ──────────────────────────────────────────
BASIC = 1
ADMIN = 2
MEALBOT = 4
COOKBOOK = 8
HAPPY_HOUR = 16
HAPPY_HOUR_TYRANT = 32
ALL_CLAIMS = BASIC | ADMIN | MEALBOT | COOKBOOK | HAPPY_HOUR | HAPPY_HOUR_TYRANT

# ── Screenshot helpers ───────────────────────────────────────────────
_SCREENSHOT_DIR: Path | None = None
_STEP = 0


def _screenshot_dir(request) -> Path:
    global _SCREENSHOT_DIR
    if _SCREENSHOT_DIR is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _SCREENSHOT_DIR = Path(__file__).parent / "screenshots" / ts
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return _SCREENSHOT_DIR


def _snap(page, name: str, request) -> Path:
    global _STEP
    _STEP += 1
    d = _screenshot_dir(request)
    path = d / f"{_STEP:03d}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


# ── DB reset helper ──────────────────────────────────────────────────
def _reset_db(db_path: str) -> None:
    """Truncate all app tables and re-seed the dev-admin account."""
    conn = sqlite3.connect(db_path)
    # Truncate domain data but keep the accounts table intact
    # (the backend's ORM caches account objects in session)
    for t in ["receipts", "HappyHourEvents", "HappyHourLocations",
              "HappyHourTyrantRotation", "account_claim_requests"]:
        conn.execute(f"DELETE FROM [{t}]")
    # Delete non-admin accounts (keep the seeded dev-admin)
    conn.execute("DELETE FROM accounts WHERE username != 'admin'")
    # Ensure dev-admin has ALL claims
    conn.execute("UPDATE accounts SET claims = ? WHERE username = 'admin'", (ALL_CLAIMS,))
    conn.commit()
    conn.close()


def _grant_claims(db_path: str, username: str, claims: int) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE accounts SET claims = ? WHERE username = ?", (claims, username))
    conn.commit()
    conn.close()


# ── OIDC helpers ─────────────────────────────────────────────────────
def _oidc_login_cookies(
    backend_url: str, oidc_issuer: str, *,
    sub: str, name: str = "Test User", email: str = "test@test.local",
    mode: str = "login",
) -> dict[str, str]:
    client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    resp = client.get(f"/api/v2/auth/{mode}/test")
    assert resp.status_code in (302, 307)
    auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
    httpx.get(auth_url, follow_redirects=False, timeout=10)
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
        "redirect_uri": qs["redirect_uri"][0],
        "state": qs["state"][0],
        "nonce": qs["nonce"][0],
        "sub": sub, "name": name, "email": email,
    })
    resp = httpx.get(approve, follow_redirects=False, timeout=10)
    assert resp.status_code == 302
    cb = urlparse(resp.headers["location"])
    client.get(f"{cb.path}?{cb.query}")
    cookies = dict(client.cookies.items())
    client.close()
    return cookies


def _inject_cookies(target, cookies: dict[str, str], url: str) -> None:
    ctx = getattr(target, "context", target)
    for k, v in cookies.items():
        ctx.add_cookies([{"name": k, "value": v, "url": url}])


def _register_and_activate(backend_url, oidc_issuer, db_path, *, sub, username, name="Test", email="t@t.local"):
    client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    resp = client.get("/api/v2/auth/register/test")
    auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
    httpx.get(auth_url, follow_redirects=False, timeout=10)
    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
        "redirect_uri": qs["redirect_uri"][0], "state": qs["state"][0],
        "nonce": qs["nonce"][0], "sub": sub, "name": name, "email": email,
    })
    resp = httpx.get(approve, follow_redirects=False, timeout=10)
    cb = urlparse(resp.headers["location"])
    client.get(f"{cb.path}?{cb.query}")
    csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
    client.post("/api/v2/auth/complete-registration", json={"username": username}, headers={"X-CSRF-Token": csrf})
    client.close()
    activate_account(db_path, username)


def _api_client(backend_url, cookies):
    """Create an authenticated httpx client for API calls."""
    c = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


def _get_csrf(client):
    return client.get("/api/v2/auth/csrf-token").json()["csrf_token"]


# ── Pytest hooks ─────────────────────────────────────────────────────
def pytest_addoption(parser):
    parser.addoption("--screenshots-dir", action="store", default=None)


@pytest.fixture(autouse=True)
def _reset_step():
    global _STEP
    _STEP = 0


# ── Test class ───────────────────────────────────────────────────────
@pytest.mark.skipif(
    not os.environ.get("RUN_VISUAL_TESTS"),
    reason="Set RUN_VISUAL_TESTS=1 to run visual approval tests",
)
class TestVisualApproval:

    # ── 01: Public pages ─────────────────────────────────────────────
    def test_01_public_pages(self, page, frontend_server, backend_db_path, request):
        """Screenshot public pages: index, login, happyhour, 404."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server

        for path, name in [("/", "index"), ("/login", "login"), ("/happyhour", "happyhour_public"), ("/auth/complete-registration", "registration_form"), ("/auth/claim-account", "claim_form"), ("/nonexistent-page", "404_page")]:
            page.goto(f"{frontend_url}{path}")
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)
            _snap(page, name, request)

    # ── 02: Registration flow ────────────────────────────────────────
    def test_02_registration_flow(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Full OIDC registration: login page -> register -> OIDC -> complete -> pending."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        frontend_port = frontend_server[1]

        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        _snap(page, "reg_01_login_page", request)

        page.locator("a", has_text="Register with Test Provider").click()
        page.wait_for_selector("button[type='submit']", timeout=10000)
        _snap(page, "reg_02_oidc_authorize", request)

        page.fill("input[name='sub']", "vis-reg-user")
        page.fill("input[name='name']", "Visual Test User")
        page.fill("input[name='email']", "vis@test.local")
        _snap(page, "reg_03_oidc_filled", request)
        page.click("button[type='submit']")

        page.wait_for_url("**/complete-registration**", timeout=10000)
        current = page.url
        if f":{frontend_port}" not in current:
            page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)
        _snap(page, "reg_04_complete_form", request)

        page.fill("#username", "visual_user")
        _snap(page, "reg_05_username_filled", request)
        page.click("#complete-registration-form button[type='submit']")
        time.sleep(1)
        _snap(page, "reg_06_pending_approval", request)

    # ── 03: Account page with claims ─────────────────────────────────
    def test_03_account_page(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Account page: profile, claims toggles, theme picker."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "account_01_full", request)

        # Toggle MEALBOT claim
        cb = page.query_selector(".claim-checkbox[data-claim=\"MEALBOT\"]")
        if cb and cb.is_checked():
            cb.click()
            time.sleep(0.8)
            _snap(page, "account_02_mealbot_off", request)
            cb.click()
            time.sleep(0.8)

        # Theme picker
        picker = page.query_selector("#theme-picker")
        if picker:
            picker.scroll_into_view_if_needed()
            time.sleep(0.3)
            _snap(page, "account_03_theme_picker", request)

    # ── 04: Mealbot with data ────────────────────────────────────────
    def test_04_mealbot(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Mealbot: create peer user, record meals, show summary & ledger."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a peer user for meal recording
        _register_and_activate(backend_url, oidc_issuer, backend_db_path,
            sub="meal-peer", username="peer", name="Peer", email="peer@test.local")
        _grant_claims(backend_db_path, "peer", BASIC | MEALBOT)

        # Login as admin
        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        # Record some meals via API so the page has data
        api = _api_client(backend_url, cookies)
        csrf = _get_csrf(api)
        for _ in range(3):
            api.post("/api/v2/mealbot/record", json={"payer": "admin", "recipient": "peer", "credits": 1}, headers={"X-CSRF-Token": csrf})
            csrf = _get_csrf(api)
        api.post("/api/v2/mealbot/record", json={"payer": "peer", "recipient": "admin", "credits": 1}, headers={"X-CSRF-Token": csrf})
        api.close()

        # Mealbot dashboard with real data
        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "mealbot_01_dashboard", request)

        # Record a meal via UI
        other_input = page.query_selector("#other-user-input")
        if other_input:
            other_input.fill("peer")
            i_paid = page.query_selector("#i-paid-btn")
            if i_paid:
                i_paid.click()
                time.sleep(1)
                _snap(page, "mealbot_02_after_record", request)

        # Individualized page
        page.goto(f"{frontend_url}/mealbot/individualized")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "mealbot_03_individualized", request)

    # ── 05: Happy Hour with data ─────────────────────────────────────
    def test_05_happyhour(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Happy Hour: create locations + event, show submit form, rotation."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        # Create location + event via API
        api = _api_client(backend_url, cookies)
        csrf = _get_csrf(api)
        loc = api.post("/api/v2/happyhour/locations", json={
            "name": "The Crafty Fox", "url": "https://craftyfox.example.com",
            "address_raw": "123 Brew Ave, Portland, OR 97201",
            "number": 123, "street_name": "Brew Ave", "city": "Portland",
            "state": "OR", "zip_code": "97201", "latitude": 45.52, "longitude": -122.68,
        }, headers={"X-CSRF-Token": csrf})
        assert loc.status_code == 201, loc.text
        loc_id = loc.json()["id"]

        csrf = _get_csrf(api)
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        evt = api.post("/api/v2/happyhour/events", json={
            "location_id": loc_id, "description": "Weekly HH at Crafty Fox!", "when": next_week,
        }, headers={"X-CSRF-Token": csrf})
        assert evt.status_code == 201, evt.text
        api.close()

        # Happy hour page with real data
        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "hh_01_with_event", request)

        # Submit section (visible because admin has TYRANT claim)
        submit = page.query_selector("#happyhour-submit-section")
        if submit and submit.is_visible():
            submit.scroll_into_view_if_needed()
            time.sleep(0.5)
            _snap(page, "hh_02_submit_form", request)

        # Locations section
        locs = page.query_selector("#happyhour-locations-section")
        if locs and locs.is_visible():
            locs.scroll_into_view_if_needed()
            time.sleep(0.5)
            _snap(page, "hh_03_locations", request)

    # ── 06: Admin dashboard ──────────────────────────────────────────
    def test_06_admin(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Admin: pending accounts, all accounts, claim requests."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a pending user
        _register_and_activate(backend_url, oidc_issuer, backend_db_path,
            sub="pending-vis", username="pending_user", name="Pending User", email="pend@test.local")
        conn = sqlite3.connect(backend_db_path)
        conn.execute("UPDATE accounts SET status = 'pending_approval' WHERE username = 'pending_user'")
        conn.commit()
        conn.close()

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "admin_01_pending", request)

        # Approve
        btn = page.query_selector(".approve-account-btn")
        if btn:
            btn.click()
            time.sleep(1)
            _snap(page, "admin_02_after_approve", request)

        # All Accounts tab
        tabs = page.query_selector_all(".admin-tab")
        if len(tabs) > 1:
            tabs[1].click()
            time.sleep(1)
            _snap(page, "admin_03_all_accounts", request)

        # Claims tab
        if len(tabs) > 2:
            tabs[2].click()
            time.sleep(1)
            _snap(page, "admin_04_claims_tab", request)

    # ── 07: Defunct account ──────────────────────────────────────────
    def test_07_defunct(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Defunct account shows read-only banner on all pages."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        _register_and_activate(backend_url, oidc_issuer, backend_db_path,
            sub="defunct-vis", username="defunctvis", name="Defunct", email="def@test.local")
        _grant_claims(backend_db_path, "defunctvis", BASIC | MEALBOT | HAPPY_HOUR)
        conn = sqlite3.connect(backend_db_path)
        conn.execute("UPDATE accounts SET status = 'defunct' WHERE username = 'defunctvis'")
        conn.commit()
        conn.close()

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="defunct-vis", name="Defunct", email="def@test.local")
        _inject_cookies(page, cookies, frontend_url)

        for path, name in [("/account", "defunct_01_account"), ("/mealbot", "defunct_02_mealbot"), ("/happyhour", "defunct_03_happyhour")]:
            page.goto(f"{frontend_url}{path}")
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            _snap(page, name, request)

    # ── 08: Theme showcase ───────────────────────────────────────────
    def test_08_themes(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Screenshot all 23 themes on the account page."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        themes = [
            "default", "light", "solarized-dark", "solarized-light",
            "nord", "dracula", "monokai", "cyberpunk", "ocean", "forest",
            "sunset", "midnight-purple", "cherry-blossom", "retro-terminal",
            "high-contrast", "warm-earth", "arctic", "neon", "paper",
            "slate", "rose-gold", "emerald", "coffee",
        ]

        # Load the page once, then switch themes via JS attribute only
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        for theme in themes:
            if theme == "default":
                page.evaluate("document.documentElement.removeAttribute('data-theme')")
            else:
                page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
            time.sleep(0.5)
            _snap(page, f"theme_{theme}", request)

    # ── 09: Mobile views ─────────────────────────────────────────────
    def test_09_mobile(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Screenshot every page at 375x812 mobile viewport."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        # Use mobile viewport on the existing page (avoids creating a separate context)
        page.set_viewport_size({"width": 375, "height": 812})

        for path, name in [("/", "mobile_index"), ("/account", "mobile_account"), ("/happyhour", "mobile_happyhour"), ("/mealbot", "mobile_mealbot"), ("/admin", "mobile_admin")]:
            page.goto(f"{frontend_url}{path}")
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            _snap(page, name, request)
            toggle = page.query_selector("#menu-toggle")
            if toggle and toggle.is_visible():
                toggle.click()
                time.sleep(0.5)
                _snap(page, f"{name}_sidebar", request)
                page.evaluate("document.getElementById('sidebar').classList.remove('open'); document.getElementById('sidebar-overlay').classList.remove('open')")
                time.sleep(0.3)

        # Restore desktop viewport
        page.set_viewport_size({"width": 1280, "height": 720})

    # ── 10: Error and redirect ───────────────────────────────────────
    def test_10_errors(self, page, frontend_server, backend_db_path, request):
        """404 page and login redirect."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server

        page.goto(f"{frontend_url}/nonexistent", timeout=60000)
        page.wait_for_load_state("networkidle")
        _snap(page, "error_404", request)

        page.goto(f"{frontend_url}/account", timeout=60000)
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        _snap(page, "error_redirect_to_login", request)

    # ── 11: OIDC rejected login ──────────────────────────────────────
    def test_11_oidc_rejected(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Login attempt for non-existent user shows error."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        frontend_port = frontend_server[1]

        page.goto(f"{frontend_url}/login", timeout=60000)
        page.wait_for_load_state("networkidle")
        _snap(page, "rejected_01_login_page", request)

        page.locator("a", has_text="Login with Test Provider").click()
        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", "unknown-user-xyz")
        page.fill("input[name='name']", "Nobody")
        page.fill("input[name='email']", "nobody@test.local")
        page.click("button[type='submit']")

        page.wait_for_load_state("networkidle", timeout=10000)
        time.sleep(1)
        current = page.url
        # Backend redirects to /login?error=... via the frontend
        if "/login" not in current:
            page.goto(f"{frontend_url}/login")
            page.wait_for_load_state("networkidle")
        _snap(page, "rejected_02_error_shown", request)

    # ── 12: Claim account flow ───────────────────────────────────────
    def test_12_claim_flow(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Claim account section on registration page."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        frontend_port = frontend_server[1]

        # Create a legacy claimable account
        conn = sqlite3.connect(backend_db_path)
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(username, email, phone_provider, account_provider, external_unique_id, claims, status) "
            "VALUES ('legacy_user', NULL, 1, 1, 'legacy-no-match', 1, 'active')"
        )
        conn.commit()
        conn.close()

        page.context.clear_cookies()
        page.goto(f"{frontend_url}/login")
        page.wait_for_selector("#login-actions a", timeout=5000)
        page.locator("a", has_text="Register with Test Provider").click()
        page.wait_for_selector("button[type='submit']", timeout=10000)
        page.fill("input[name='sub']", "claim-test-user")
        page.fill("input[name='name']", "Claim Tester")
        page.fill("input[name='email']", "claim@test.local")
        page.click("button[type='submit']")

        page.wait_for_url("**/complete-registration**", timeout=10000)
        current = page.url
        if f":{frontend_port}" not in current:
            page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)
        time.sleep(1.5)
        _snap(page, "claim_01_registration_with_claim", request)

        claim_form = page.query_selector("#claim-account-form")
        if claim_form:
            page.fill("#claim-username", "legacy_user")
            _snap(page, "claim_02_form_filled", request)
            page.click("#claim-account-form button[type='submit']")
            time.sleep(1)
            _snap(page, "claim_03_submitted", request)

    # ── 13: Disaster recovery ────────────────────────────────────────
    def test_13_recovery(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path, request,
    ):
        """Recovery: cancel event, reschedule, void mealbot record."""
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a peer for mealbot
        _register_and_activate(backend_url, oidc_issuer, backend_db_path,
            sub="recov-peer", username="recov_peer", name="Peer", email="rpeer@test.local")
        _grant_claims(backend_db_path, "recov_peer", BASIC | MEALBOT)

        cookies = _oidc_login_cookies(backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local")
        _inject_cookies(page, cookies, frontend_url)

        api = _api_client(backend_url, cookies)

        # Create location + event
        csrf = _get_csrf(api)
        loc = api.post("/api/v2/happyhour/locations", json={
            "name": "Wrong Venue", "address_raw": "1 Mistake Ave, Portland, OR 97201",
            "number": 1, "street_name": "Mistake Ave", "city": "Portland",
            "state": "OR", "zip_code": "97201", "latitude": 45.52, "longitude": -122.68,
        }, headers={"X-CSRF-Token": csrf})
        assert loc.status_code == 201, loc.text

        csrf = _get_csrf(api)
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        evt = api.post("/api/v2/happyhour/events", json={
            "location_id": loc.json()["id"], "description": "Wrong venue!", "when": next_week,
        }, headers={"X-CSRF-Token": csrf})
        assert evt.status_code == 201, evt.text
        event_id = evt.json()["id"]

        # Screenshot with Cancel button
        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        _snap(page, "recovery_01_cancel_btn_visible", request)

        # Cancel via API
        csrf = _get_csrf(api)
        api.delete(f"/api/v2/happyhour/events/{event_id}", headers={"X-CSRF-Token": csrf})
        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "recovery_02_after_cancel", request)

        # Create a meal and void it
        csrf = _get_csrf(api)
        api.post("/api/v2/mealbot/record", json={"payer": "admin", "recipient": "recov_peer", "credits": 1}, headers={"X-CSRF-Token": csrf})

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        _snap(page, "recovery_03_mealbot_with_void", request)

        # Void via API
        ledger = api.get("/api/v2/mealbot/ledger")
        if ledger.status_code == 200 and ledger.json().get("items"):
            rid = ledger.json()["items"][0]["id"]
            csrf = _get_csrf(api)
            api.delete(f"/api/v2/mealbot/record/{rid}", headers={"X-CSRF-Token": csrf})

        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "recovery_04_after_void", request)

        api.close()
