"""Visual Timeline Tests — Screenshot Every Page in Complete User Flows.

Each test captures a numbered sequence of screenshots representing every
page an end-user sees during a particular workflow.  Together, these form
a visual timeline that can be reviewed without running the application.

Screenshots are organised into flow-specific sub-directories::

    screenshots/{timestamp}/
        01_account_registration/
            001_login_page.png
            002_oidc_register_form.png
            ...
        02_account_claim/
            001_login_page.png
            ...

Run::

    RUN_VISUAL_TESTS=1 pytest test_visual_approval.py -v
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

from helpers import activate_account, rewrite_oidc_url

# ── Claim bitmask constants ──────────────────────────────────────────
BASIC = 1
ADMIN = 2
MEALBOT = 4
COOKBOOK = 8
HAPPY_HOUR = 16
HAPPY_HOUR_TYRANT = 32
ALL_CLAIMS = BASIC | ADMIN | MEALBOT | COOKBOOK | HAPPY_HOUR | HAPPY_HOUR_TYRANT

# ── Session-wide screenshot root ─────────────────────────────────────
_SESSION_DIR: Path | None = None


def _session_dir() -> Path:
    global _SESSION_DIR
    if _SESSION_DIR is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _SESSION_DIR = Path(__file__).parent / "screenshots" / ts
    return _SESSION_DIR


# ── FlowRecorder — per-flow screenshot sequencer ─────────────────────
class FlowRecorder:
    """Manages numbered screenshots for a single flow."""

    def __init__(self, flow_name: str) -> None:
        self.dir = _session_dir() / flow_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.step = 0

    def snap(self, page, description: str) -> Path:
        """Take a full-page screenshot and return its path."""
        self.step += 1
        path = self.dir / f"{self.step:03d}_{description}.png"
        page.screenshot(path=str(path), full_page=True)
        return path


# ── DB helpers ────────────────────────────────────────────────────────

def _reset_db(db_path: str) -> None:
    """Truncate all app tables and re-seed the dev-admin account."""
    conn = sqlite3.connect(db_path)
    for t in [
        "receipts",
        "HappyHourEvents",
        "HappyHourLocations",
        "HappyHourTyrantRotation",
        "account_claim_requests",
    ]:
        conn.execute(f"DELETE FROM [{t}]")
    conn.execute("DELETE FROM accounts WHERE username != 'admin'")
    conn.execute(
        "UPDATE accounts SET claims = ? WHERE username = 'admin'",
        (ALL_CLAIMS,),
    )
    conn.commit()
    conn.close()


def _grant_claims(db_path: str, username: str, claims: int) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE accounts SET claims = ? WHERE username = ?", (claims, username))
    conn.commit()
    conn.close()


def _set_status(db_path: str, username: str, status: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE accounts SET status = ? WHERE username = ?", (status, username))
    conn.commit()
    conn.close()


def _insert_legacy_account(db_path: str, username: str) -> None:
    """Insert a claimable legacy account with no external identity."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO accounts "
        "(username, email, phone_provider, account_provider, external_unique_id, claims, status) "
        "VALUES (?, NULL, 1, 1, 'legacy-placeholder', 1, 'active')",
        (username,),
    )
    conn.commit()
    conn.close()


# ── OIDC / API helpers (headless, for data setup) ────────────────────

def _oidc_login_cookies(
    backend_url: str,
    oidc_issuer: str,
    *,
    sub: str,
    name: str = "Test User",
    email: str = "test@test.local",
    mode: str = "login",
) -> dict[str, str]:
    """Perform an OIDC login/register headlessly and return cookies."""
    client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    try:
        resp = client.get(f"/api/v2/auth/{mode}/test")
        assert resp.status_code in (302, 307)
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        with httpx.Client(timeout=10) as oidc_client:
            oidc_client.get(auth_url, follow_redirects=False)
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
            resp = oidc_client.get(approve, follow_redirects=False)
        assert resp.status_code == 302
        cb = urlparse(resp.headers["location"])
        client.get(f"{cb.path}?{cb.query}")
        cookies = dict(client.cookies.items())
    finally:
        client.close()
    return cookies


def _inject_cookies(target, cookies: dict[str, str], url: str) -> None:
    ctx = getattr(target, "context", target)
    for k, v in cookies.items():
        ctx.add_cookies([{"name": k, "value": v, "url": url}])


def _register_and_activate(
    backend_url, oidc_issuer, db_path, *, sub, username, name="Test", email="t@t.local",
):
    """Register a user headlessly and activate them via DB."""
    client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    try:
        resp = client.get("/api/v2/auth/register/test")
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        with httpx.Client(timeout=10) as oidc_client:
            oidc_client.get(auth_url, follow_redirects=False)
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
            resp = oidc_client.get(approve, follow_redirects=False)
        cb = urlparse(resp.headers["location"])
        client.get(f"{cb.path}?{cb.query}")
        csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        client.post(
            "/api/v2/auth/complete-registration",
            json={"username": username},
            headers={"X-CSRF-Token": csrf},
        )
    finally:
        client.close()
    activate_account(db_path, username)


def _api_client(backend_url: str, cookies: dict) -> httpx.Client:
    c = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
    for k, v in cookies.items():
        c.cookies.set(k, v)
    return c


def _get_csrf(client: httpx.Client) -> str:
    return client.get("/api/v2/auth/csrf-token").json()["csrf_token"]


# ── Browser-driven OIDC flow helpers ─────────────────────────────────

def _browser_goto_login(page, frontend_url: str) -> None:
    """Navigate to the login page and wait for the links to render."""
    page.goto(f"{frontend_url}/login")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#login-actions a", timeout=5000)


def _browser_oidc_fill(page, *, sub: str, name: str, email: str) -> None:
    """Fill in the mock OIDC authorize form (does NOT click submit)."""
    page.wait_for_selector("button[type='submit']", timeout=10000)
    page.fill("input[name='sub']", sub)
    page.fill("input[name='name']", name)
    page.fill("input[name='email']", email)


def _browser_oidc_submit_and_wait(page, frontend_url: str) -> str:
    """Click Authorize on the OIDC form and handle the redirect."""
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle", timeout=15000)
    time.sleep(1)

    current = page.url
    frontend_port = str(urlparse(frontend_url).port)

    if frontend_port and f":{frontend_port}" in current:
        return urlparse(current).path

    parsed = urlparse(current)
    target = f"{frontend_url}{parsed.path}"
    if parsed.query:
        target += f"?{parsed.query}"
    page.goto(target)
    page.wait_for_load_state("networkidle")
    return parsed.path


def _browser_login(
    page, frontend_url: str, *, sub: str, name: str, email: str,
) -> bool:
    """Drive the full browser login flow."""
    _browser_goto_login(page, frontend_url)
    page.locator("a", has_text="Login with Test Provider").click()
    _browser_oidc_fill(page, sub=sub, name=name, email=email)
    final_path = _browser_oidc_submit_and_wait(page, frontend_url)
    return "/account" in final_path or final_path == "/"


def _browser_logout(page, frontend_url: str) -> None:
    """Click the sidebar logout link."""
    logout = page.locator("#nav-logout")
    if logout.is_visible():
        logout.click()
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
    else:
        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")


def _clear_user(page) -> None:
    """Clear cookies so the next navigation is unauthenticated."""
    page.context.clear_cookies()


# ── Skip guard ────────────────────────────────────────────────────────

_skip = pytest.mark.skipif(
    not os.environ.get("RUN_VISUAL_TESTS"),
    reason="Set RUN_VISUAL_TESTS=1 to run visual approval tests",
)


# ═══════════════════════════════════════════════════════════════════════
# Flow 01 — Account Registration & Admin Approval
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow01AccountRegistration:
    def test_account_registration_and_approval(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        flow = FlowRecorder("01_account_registration")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Register with Test Provider").click()
        _browser_oidc_fill(page, sub="new-user-01", name="New User", email="new@test.local")
        flow.snap(page, "oidc_register_form")

        page.click("button[type='submit']")
        page.wait_for_url("**/complete-registration**", timeout=15000)
        frontend_port = str(frontend_server[1])
        if f":{frontend_port}" not in page.url:
            page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)
        time.sleep(0.5)
        flow.snap(page, "complete_registration_empty")

        page.fill("#username", "new_user")
        flow.snap(page, "complete_registration_filled")

        page.click('#complete-registration-form button[type="submit"]')
        page.locator("#complete-registration-result").wait_for(state="visible", timeout=5000)
        time.sleep(0.5)
        flow.snap(page, "pending_approval_message")

        _clear_user(page)
        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page_retry")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="new-user-01", name="New User", email="new@test.local")
        flow.snap(page, "oidc_login_attempt")

        _browser_oidc_submit_and_wait(page, frontend_url)
        time.sleep(0.5)
        flow.snap(page, "login_error_pending_approval")

        _clear_user(page)
        _browser_goto_login(page, frontend_url)
        flow.snap(page, "admin_login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="dev-admin", name="Admin", email="admin@dev.local")
        flow.snap(page, "admin_oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "admin_account_page")

        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        flow.snap(page, "admin_pending_accounts")

        approve_btn = page.locator(".approve-account-btn").first
        if approve_btn.is_visible():
            approve_btn.click()
            time.sleep(1)
        flow.snap(page, "admin_account_approved")

        _browser_logout(page, frontend_url)
        time.sleep(0.5)
        flow.snap(page, "admin_logged_out")

        _clear_user(page)
        _browser_goto_login(page, frontend_url)
        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="new-user-01", name="New User", email="new@test.local")
        flow.snap(page, "user_oidc_login_approved")

        _browser_oidc_submit_and_wait(page, frontend_url)
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "user_account_page_approved")


# ═══════════════════════════════════════════════════════════════════════
# Flow 02 — Account Claim
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow02AccountClaim:
    def test_account_claim_flow(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        frontend_port = str(frontend_server[1])
        flow = FlowRecorder("02_account_claim")

        _insert_legacy_account(backend_db_path, "legacy_user")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Register with Test Provider").click()
        _browser_oidc_fill(page, sub="claimer-01", name="Claim User", email="claim@test.local")
        flow.snap(page, "oidc_register_form")

        page.click("button[type='submit']")
        page.wait_for_url("**/complete-registration**", timeout=15000)
        if f":{frontend_port}" not in page.url:
            page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_selector("#complete-registration-form", timeout=5000)
        time.sleep(1.5)

        claim_form = page.query_selector("#claim-account-form")
        if claim_form:
            claim_form.scroll_into_view_if_needed()
            time.sleep(0.5)
            flow.snap(page, "complete_registration_claim_visible")

            page.fill("#claim-username", "legacy_user")
            flow.snap(page, "claim_form_filled")

            page.click("#claim-account-form button[type='submit']")
            time.sleep(1)
            flow.snap(page, "claim_submitted")
        else:
            flow.snap(page, "claim_section_not_rendered")

        _clear_user(page)
        _browser_login(
            page, frontend_url, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        flow.snap(page, "admin_logged_in")

        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        claims_tab = page.locator(".admin-tab[data-tab='claims']")
        if claims_tab.count() > 0:
            claims_tab.click()
            time.sleep(1)
        flow.snap(page, "admin_claims_tab")

        approve_btn = page.locator(".approve-claim-btn").first
        if approve_btn.count() > 0 and approve_btn.is_visible():
            approve_btn.click()
            time.sleep(1)
        flow.snap(page, "admin_claim_approved")

        _browser_logout(page, frontend_url)
        flow.snap(page, "admin_logged_out")

        _clear_user(page)
        _browser_login(
            page, frontend_url, sub="claimer-01", name="Claim User", email="claim@test.local",
        )
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "claimant_account_page")


# ═══════════════════════════════════════════════════════════════════════
# Flow 03 — Mealbot Usage
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow03Mealbot:
    def test_mealbot_usage(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("03_mealbot")

        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="meal-peer", username="peer", name="Peer User", email="peer@test.local",
        )
        _grant_claims(backend_db_path, "peer", BASIC | MEALBOT)

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="dev-admin", name="Admin", email="admin@dev.local")
        flow.snap(page, "oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        flow.snap(page, "mealbot_empty")

        other_input = page.query_selector("#other-user-input")
        if other_input:
            other_input.fill("peer")
            flow.snap(page, "mealbot_record_form_filled")

            i_paid = page.query_selector("#i-paid-btn")
            if i_paid:
                i_paid.click()
                time.sleep(1.5)

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        api = _api_client(backend_url, cookies)
        for _ in range(2):
            csrf = _get_csrf(api)
            api.post(
                "/api/v2/mealbot/record",
                json={"payer": "admin", "recipient": "peer", "credits": 1},
                headers={"X-CSRF-Token": csrf},
            )
        csrf = _get_csrf(api)
        api.post(
            "/api/v2/mealbot/record",
            json={"payer": "peer", "recipient": "admin", "credits": 1},
            headers={"X-CSRF-Token": csrf},
        )
        api.close()

        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        flow.snap(page, "mealbot_with_data")

        page.goto(f"{frontend_url}/mealbot/individualized")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "mealbot_individualized")

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "mealbot_before_void")

        page.on("dialog", lambda d: d.accept())
        void_btn = page.locator(".void-record-btn").first
        if void_btn.count() > 0 and void_btn.is_visible():
            void_btn.click()
            page.wait_for_selector("#mealbot-record-result:not(:empty)", timeout=5000)
            time.sleep(1)
            flow.snap(page, "mealbot_after_void")
        else:
            flow.snap(page, "mealbot_no_void_btn")


# ═══════════════════════════════════════════════════════════════════════
# Flow 04 — Happy Hour Lifecycle
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow04HappyHour:
    def test_happyhour_lifecycle(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("04_happy_hour")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="dev-admin", name="Admin", email="admin@dev.local")
        flow.snap(page, "oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        flow.snap(page, "happyhour_empty")

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        api = _api_client(backend_url, cookies)
        csrf = _get_csrf(api)
        loc = api.post(
            "/api/v2/happyhour/locations",
            json={
                "name": "The Crafty Fox",
                "url": "https://craftyfox.example.com",
                "address_raw": "123 Brew Ave, Portland, OR 97201",
                "number": 123, "street_name": "Brew Ave", "city": "Portland",
                "state": "OR", "zip_code": "97201",
                "latitude": 45.52, "longitude": -122.68,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert loc.status_code == 201, loc.text

        csrf = _get_csrf(api)
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        evt = api.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc.json()["id"],
                "description": "Weekly HH at Crafty Fox!",
                "when": next_week,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert evt.status_code == 201, evt.text
        event_id = evt.json()["id"]
        api.close()

        page.reload()
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
        flow.snap(page, "happyhour_with_event")

        page.on("dialog", lambda d: d.accept())
        cancel_btn = page.locator(".cancel-event-btn").first
        if cancel_btn.count() > 0 and cancel_btn.is_visible():
            cancel_btn.click()
            page.wait_for_selector("#happyhour-result:not(:empty)", timeout=5000)
            time.sleep(1)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
        else:
            cookies2 = _oidc_login_cookies(
                backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local",
            )
            api2 = _api_client(backend_url, cookies2)
            csrf2 = _get_csrf(api2)
            api2.delete(f"/api/v2/happyhour/events/{event_id}", headers={"X-CSRF-Token": csrf2})
            api2.close()
            page.reload()
            page.wait_for_load_state("networkidle")
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
        flow.snap(page, "happyhour_after_cancel")


# ═══════════════════════════════════════════════════════════════════════
# Flow 05 — Account Self-Service
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow05AccountSelfService:
    def test_account_self_service(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        flow = FlowRecorder("05_account_self_service")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="dev-admin", name="Admin", email="admin@dev.local")
        flow.snap(page, "oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)
        flow.snap(page, "account_profile")

        claims_form = page.query_selector("#claims-form")
        if claims_form:
            claims_form.scroll_into_view_if_needed()
            time.sleep(0.5)
            flow.snap(page, "account_claims_section")

            cb = page.query_selector('.claim-checkbox[data-claim="MEALBOT"]')
            if cb:
                cb.click()
                time.sleep(0.8)
                flow.snap(page, "account_claim_toggled")

        swatch = page.query_selector('.theme-swatch[data-theme-name="dracula"]')
        if swatch:
            swatch.click()
            time.sleep(0.5)
        else:
            page.evaluate("document.documentElement.setAttribute('data-theme', 'dracula')")
            time.sleep(0.3)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)
        flow.snap(page, "account_theme_dracula")


# ═══════════════════════════════════════════════════════════════════════
# Flow 06 — Defunct Account (Read-only)
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow06DefunctAccount:
    def test_defunct_account(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("06_defunct_account")

        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="defunct-user", username="defunct_user", name="Defunct", email="def@test.local",
        )
        _grant_claims(backend_db_path, "defunct_user", BASIC | MEALBOT | HAPPY_HOUR)
        _set_status(backend_db_path, "defunct_user", "defunct")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="defunct-user", name="Defunct", email="def@test.local")
        flow.snap(page, "oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)
        time.sleep(0.5)
        flow.snap(page, "login_defunct_error")

        _clear_user(page)
        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer, sub="defunct-user", name="Defunct", email="def@test.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "defunct_account_page")

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "defunct_mealbot")

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        flow.snap(page, "defunct_happyhour")


# ═══════════════════════════════════════════════════════════════════════
# Flow 07 — Login Rejection
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow07LoginRejection:
    def test_login_rejection(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        flow = FlowRecorder("07_login_rejection")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="nobody-xyz", name="Nobody", email="nobody@test.local")
        flow.snap(page, "oidc_unknown_user")

        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(1)
        flow.snap(page, "authentication_error_raw")

        page.goto(f"{frontend_url}/login?error=Authentication+failed")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        flow.snap(page, "login_page_with_error")


# ═══════════════════════════════════════════════════════════════════════
# Flow 08 — Public Pages & Redirects
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow08PublicPages:
    def test_public_pages(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        flow = FlowRecorder("08_public_pages")

        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        flow.snap(page, "login_page")

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        flow.snap(page, "happyhour_public")

        page.goto(f"{frontend_url}/nonexistent-page")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        flow.snap(page, "page_404")

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        flow.snap(page, "redirect_to_login")

        _browser_login(
            page, frontend_url, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        page.goto(f"{frontend_url}/")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        flow.snap(page, "index_authenticated")


# ═══════════════════════════════════════════════════════════════════════
# Flow 09 — Admin Dashboard
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow09AdminDashboard:
    def test_admin_dashboard(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("09_admin_dashboard")

        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="active-vis", username="active_user", name="Active", email="active@test.local",
        )
        _grant_claims(backend_db_path, "active_user", BASIC | MEALBOT)

        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="pending-vis", username="pending_user", name="Pending", email="pend@test.local",
        )
        _set_status(backend_db_path, "pending_user", "pending_approval")

        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="banned-vis", username="banned_user", name="Banned", email="ban@test.local",
        )
        _set_status(backend_db_path, "banned_user", "banned")

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="dev-admin", name="Admin", email="admin@dev.local")
        flow.snap(page, "oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)

        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        flow.snap(page, "admin_pending_tab")

        approve_btn = page.locator(".approve-account-btn").first
        if approve_btn.count() > 0 and approve_btn.is_visible():
            approve_btn.click()
            time.sleep(1)
        flow.snap(page, "admin_after_approve")

        all_tab = page.locator(".admin-tab[data-tab='accounts']")
        if all_tab.count() > 0:
            all_tab.click()
            time.sleep(1)
        flow.snap(page, "admin_all_accounts")

        claims_tab = page.locator(".admin-tab[data-tab='claims']")
        if claims_tab.count() > 0:
            claims_tab.click()
            time.sleep(1)
        flow.snap(page, "admin_claims_tab")


# ═══════════════════════════════════════════════════════════════════════
# Flow 10 — Disaster Recovery
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow10DisasterRecovery:
    def test_disaster_recovery(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("10_disaster_recovery")

        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="recov-peer", username="recov_peer", name="Peer", email="rpeer@test.local",
        )
        _grant_claims(backend_db_path, "recov_peer", BASIC | MEALBOT)

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        api = _api_client(backend_url, cookies)

        csrf = _get_csrf(api)
        loc = api.post(
            "/api/v2/happyhour/locations",
            json={
                "name": "Wrong Venue",
                "address_raw": "1 Mistake Ave, Portland, OR 97201",
                "number": 1, "street_name": "Mistake Ave", "city": "Portland",
                "state": "OR", "zip_code": "97201",
                "latitude": 45.52, "longitude": -122.68,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert loc.status_code == 201, loc.text

        csrf = _get_csrf(api)
        next_week = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        evt = api.post(
            "/api/v2/happyhour/events",
            json={
                "location_id": loc.json()["id"],
                "description": "Wrong venue!",
                "when": next_week,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert evt.status_code == 201, evt.text

        for _ in range(3):
            csrf = _get_csrf(api)
            api.post(
                "/api/v2/mealbot/record",
                json={"payer": "admin", "recipient": "recov_peer", "credits": 1},
                headers={"X-CSRF-Token": csrf},
            )
        api.close()

        _browser_goto_login(page, frontend_url)
        flow.snap(page, "login_page")

        page.locator("a", has_text="Login with Test Provider").click()
        _browser_oidc_fill(page, sub="dev-admin", name="Admin", email="admin@dev.local")
        flow.snap(page, "oidc_login")

        _browser_oidc_submit_and_wait(page, frontend_url)

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
        flow.snap(page, "happyhour_before_cancel")

        page.on("dialog", lambda d: d.accept())
        cancel_btn = page.locator(".cancel-event-btn").first
        if cancel_btn.count() > 0 and cancel_btn.is_visible():
            cancel_btn.click()
            page.wait_for_selector("#happyhour-result:not(:empty)", timeout=5000)
            time.sleep(1)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
        flow.snap(page, "happyhour_after_cancel")

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        flow.snap(page, "mealbot_before_void")

        void_btn = page.locator(".void-record-btn").first
        if void_btn.count() > 0 and void_btn.is_visible():
            void_btn.click()
            page.wait_for_selector("#mealbot-record-result:not(:empty)", timeout=5000)
            time.sleep(1)
        flow.snap(page, "mealbot_after_void")


# ═══════════════════════════════════════════════════════════════════════
# Flow 11 — Mobile Responsive Views
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow11MobileViews:
    def test_mobile_views(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("11_mobile_views")

        page.set_viewport_size({"width": 375, "height": 812})

        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        flow.snap(page, "mobile_login")

        toggle = page.query_selector("#menu-toggle")
        if toggle and toggle.is_visible():
            toggle.click()
            time.sleep(0.5)
            flow.snap(page, "mobile_login_sidebar_open")
            page.evaluate(
                "document.getElementById('sidebar').classList.remove('open');"
                "document.getElementById('sidebar-overlay').classList.remove('open');"
            )
            time.sleep(0.3)

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        for path, name in [
            ("/account", "mobile_account"),
            ("/mealbot", "mobile_mealbot"),
            ("/happyhour", "mobile_happyhour"),
            ("/admin", "mobile_admin"),
        ]:
            page.goto(f"{frontend_url}{path}")
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            flow.snap(page, name)

            toggle = page.query_selector("#menu-toggle")
            if toggle and toggle.is_visible():
                toggle.click()
                time.sleep(0.5)
                flow.snap(page, f"{name}_sidebar_open")
                page.evaluate(
                    "document.getElementById('sidebar').classList.remove('open');"
                    "document.getElementById('sidebar-overlay').classList.remove('open');"
                )
                time.sleep(0.3)

        page.set_viewport_size({"width": 1280, "height": 720})


# ═══════════════════════════════════════════════════════════════════════
# Flow 12 — Theme Showcase
# ═══════════════════════════════════════════════════════════════════════

@_skip
class TestFlow12ThemeShowcase:
    THEMES = [
        "default", "light", "solarized-dark", "solarized-light",
        "nord", "dracula", "monokai", "cyberpunk", "ocean", "forest",
        "sunset", "midnight-purple", "cherry-blossom", "retro-terminal",
        "high-contrast", "warm-earth", "arctic", "neon", "paper",
        "slate", "rose-gold", "emerald", "coffee",
    ]

    def test_theme_showcase(
        self, page, frontend_server, backend_server, oidc_server, backend_db_path,
    ):
        _reset_db(backend_db_path)
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server
        flow = FlowRecorder("12_theme_showcase")

        cookies = _oidc_login_cookies(
            backend_url, oidc_issuer, sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        _inject_cookies(page, cookies, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        for theme in self.THEMES:
            if theme == "default":
                page.evaluate("document.documentElement.removeAttribute('data-theme')")
            else:
                page.evaluate(
                    f"document.documentElement.setAttribute('data-theme', '{theme}')"
                )
            time.sleep(0.5)
            flow.snap(page, f"theme_{theme}")
