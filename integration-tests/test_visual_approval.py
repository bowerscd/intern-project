"""Visual Timeline Tests — Screenshot Every Page in Complete User Flows.

Each test captures a numbered sequence of screenshots representing every
page an end-user sees during a particular workflow.  Together, these form
a visual timeline that can be reviewed without running the application.

Every ``FlowRecorder.snap()`` call cycles all 23 CSS themes, producing
one screenshot per theme in per-theme sub-directories::

    screenshots/{timestamp}/
        01_account_registration_t01_default/
            001_login_page.png
            002_oidc_register_form.png
            ...
        01_account_registration_t02_light/
            001_login_page.png
            ...

Serve the ``screenshots/`` directory and open ``viewer.html`` to browse
all runs, flows, and themes interactively (Space cycles themes).

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

THEMES = [
    "default", "light", "solarized-dark", "solarized-light",
    "nord", "dracula", "monokai", "cyberpunk", "ocean", "forest",
    "sunset", "midnight-purple", "cherry-blossom", "retro-terminal",
    "high-contrast", "warm-earth", "arctic", "neon", "paper",
    "slate", "rose-gold", "emerald", "coffee",
]


def _session_dir() -> Path:
    global _SESSION_DIR
    if _SESSION_DIR is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _SESSION_DIR = Path(__file__).parent / "screenshots" / ts
    return _SESSION_DIR


def _apply_theme(page, theme: str) -> None:
    """Apply a CSS theme by setting data-theme on <html>."""
    if theme == "default":
        page.evaluate(
            "document.documentElement.removeAttribute('data-theme')"
        )
    else:
        page.evaluate(
            "document.documentElement.setAttribute("
            f"'data-theme', '{theme}')"
        )


# ── FlowRecorder — per-flow screenshot sequencer ─────────────────────
class FlowRecorder:
    """Manages numbered screenshots for a single flow.

    Every ``snap()`` call cycles all 23 themes, taking one screenshot
    per theme into per-theme sub-directories::

        {flow_name}_t01_default/001_foo.png
        {flow_name}_t02_light/001_foo.png
        …

    The ``default`` theme is restored after each snap so subsequent
    browser interactions are unaffected.
    """

    def __init__(self, flow_name: str) -> None:
        self.flow_name = flow_name
        self.step = 0
        self._theme_dirs: dict[str, Path] = {}
        for idx, theme in enumerate(THEMES, start=1):
            d = _session_dir() / f"{flow_name}_t{idx:02d}_{theme}"
            d.mkdir(parents=True, exist_ok=True)
            self._theme_dirs[theme] = d

    def snap(self, page, description: str) -> Path:
        """Cycle all themes and screenshot each; return default-theme path."""
        self.step += 1
        first_path: Path | None = None
        for theme in THEMES:
            _apply_theme(page, theme)
            page.evaluate("document.body.offsetHeight")
            time.sleep(0.15)
            path = self._theme_dirs[theme] / f"{self.step:03d}_{description}.png"
            page.screenshot(path=str(path), full_page=True)
            if first_path is None:
                first_path = path
        # Restore default so subsequent interactions are unaffected
        _apply_theme(page, "default")
        assert first_path is not None
        return first_path


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

def _seed_showcase_data(
    backend_url: str,
    oidc_issuer: str,
    db_path: str,
) -> None:
    """Populate the database with realistic data for theme screenshots.

    Creates additional users, happy-hour locations, upcoming + past events,
    mealbot records, tyrant rotation entries, and a pending account-claim
    request so that every page has visible rows/tables/cards.
    """
    # ── Create extra users ────────────────────────────────────────────
    users = [
        ("user-alice", "alice", "Alice Chen", "alice@example.com"),
        ("user-bob", "bob", "Bob Martinez", "bob@example.com"),
        ("user-carol", "carol", "Carol Nguyen", "carol@example.com"),
    ]
    for sub, username, name, email in users:
        _register_and_activate(
            backend_url, oidc_issuer, db_path,
            sub=sub, username=username, name=name, email=email,
        )
        _grant_claims(db_path, username, BASIC | MEALBOT | HAPPY_HOUR)

    # One user left pending (for the admin page's "Pending Accounts" tab)
    _register_and_activate(
        backend_url, oidc_issuer, db_path,
        sub="user-pending", username="pendinguser", name="Pending Pete",
        email="pete@example.com",
    )
    _set_status(db_path, "pendinguser", "pending_approval")

    # ── Admin API client ──────────────────────────────────────────────
    cookies = _oidc_login_cookies(
        backend_url, oidc_issuer,
        sub="dev-admin", name="Admin", email="admin@dev.local",
    )
    api = _api_client(backend_url, cookies)

    # ── Happy-Hour locations ──────────────────────────────────────────
    locations_data = [
        {
            "name": "The Crafty Fox",
            "url": "https://craftyfox.example.com",
            "address_raw": "123 Brew Ave, Portland, OR 97201",
            "number": 123, "street_name": "Brew Ave", "city": "Portland",
            "state": "OR", "zip_code": "97201",
            "latitude": 45.52, "longitude": -122.68,
        },
        {
            "name": "Sunset Taphouse",
            "url": "https://sunsettap.example.com",
            "address_raw": "456 Hilltop Rd, Portland, OR 97214",
            "number": 456, "street_name": "Hilltop Rd", "city": "Portland",
            "state": "OR", "zip_code": "97214",
            "latitude": 45.51, "longitude": -122.64,
        },
        {
            "name": "NW Barrel Room",
            "url": "https://nwbarrel.example.com",
            "address_raw": "789 Pearl St, Portland, OR 97209",
            "number": 789, "street_name": "Pearl St", "city": "Portland",
            "state": "OR", "zip_code": "97209",
            "latitude": 45.53, "longitude": -122.68,
        },
        {
            "name": "Hawthorne Hideaway",
            "url": None,
            "address_raw": "1010 Hawthorne Blvd, Portland, OR 97214",
            "number": 1010, "street_name": "Hawthorne Blvd", "city": "Portland",
            "state": "OR", "zip_code": "97214",
            "latitude": 45.51, "longitude": -122.63,
        },
    ]
    location_ids = []
    for loc_data in locations_data:
        csrf = _get_csrf(api)
        resp = api.post(
            "/api/v2/happyhour/locations",
            json=loc_data,
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201, resp.text
        location_ids.append(resp.json()["id"])

    # ── Happy-Hour events (1 upcoming via API, 3 past via direct SQL) ──
    now = datetime.now(timezone.utc)

    # Upcoming event — use API (validates future date)
    csrf = _get_csrf(api)
    next_week = (now + timedelta(days=5)).isoformat()
    resp = api.post(
        "/api/v2/happyhour/events",
        json={
            "location_id": location_ids[0],
            "description": "Friday Happy Hour at Crafty Fox!",
            "when": next_week,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201, resp.text

    # ── Mealbot records ───────────────────────────────────────────────
    meal_records = [
        ("admin", "alice", 1),
        ("admin", "bob", 1),
        ("alice", "admin", 1),
        ("bob", "carol", 1),
        ("carol", "alice", 1),
        ("admin", "carol", 1),
        ("bob", "admin", 1),
    ]
    for payer, recipient, credits in meal_records:
        csrf = _get_csrf(api)
        api.post(
            "/api/v2/mealbot/record",
            json={"payer": payer, "recipient": recipient, "credits": credits},
            headers={"X-CSRF-Token": csrf},
        )

    api.close()

    # ── All remaining data via direct SQL (single connection) ─────────
    # Insert a legacy account first (uses its own connection internally)
    _insert_legacy_account(db_path, "oldtimer")

    conn = sqlite3.connect(db_path, timeout=10)

    # Past events (API rejects past dates)
    admin_id = conn.execute(
        "SELECT id FROM accounts WHERE username = 'admin'"
    ).fetchone()[0]
    past_events = [
        (location_ids[1], "Last week's meetup at Sunset Taphouse",
         (now - timedelta(days=7)).isoformat(),
         (now - timedelta(days=7)).strftime("%G-W%V"), admin_id),
        (location_ids[2], "Double-pour night at NW Barrel Room",
         (now - timedelta(days=14)).isoformat(),
         (now - timedelta(days=14)).strftime("%G-W%V"), admin_id),
        (location_ids[3], "Trivia & Brews at Hawthorne Hideaway",
         (now - timedelta(days=21)).isoformat(),
         (now - timedelta(days=21)).strftime("%G-W%V"), admin_id),
    ]
    for loc_id, desc, when, week_of, tyrant_id in past_events:
        conn.execute(
            "INSERT OR IGNORE INTO HappyHourEvents "
            "(LocationID, Description, [When], week_of, TyrantID, AutoSelected) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (loc_id, desc, when, week_of, tyrant_id),
        )

    # Tyrant rotation entries
    alice_id = conn.execute(
        "SELECT id FROM accounts WHERE username = 'alice'"
    ).fetchone()[0]
    bob_id = conn.execute(
        "SELECT id FROM accounts WHERE username = 'bob'"
    ).fetchone()[0]
    carol_id = conn.execute(
        "SELECT id FROM accounts WHERE username = 'carol'"
    ).fetchone()[0]

    rotation_rows = [
        (admin_id, 1, 1, "chosen"),
        (alice_id, 1, 2, "chosen"),
        (bob_id, 1, 3, "missed"),
        (carol_id, 1, 4, "pending"),
        (admin_id, 1, 5, "scheduled"),
        (alice_id, 1, 6, "scheduled"),
    ]
    for acct_id, cycle, position, status in rotation_rows:
        conn.execute(
            "INSERT INTO HappyHourTyrantRotation "
            "(account_id, cycle, position, status, assigned_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (acct_id, cycle, position, status, now.isoformat()),
        )

    # Pending account-claim request (for admin Claims tab)
    oldtimer_id = conn.execute(
        "SELECT id FROM accounts WHERE username = 'oldtimer'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO account_claim_requests "
        "(requester_provider, requester_external_id, requester_name, "
        " requester_email, target_account_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "claimant-ext-id", "Claimant User", "claimant@example.com",
         oldtimer_id, "pending", now.isoformat()),
    )
    conn.commit()
    conn.close()


@_skip
class TestFlow12ThemeShowcase:
    """Capture ~33 screenshots per theme across 6 phases.

    Uses the theme-aware FlowRecorder which automatically cycles all 23
    themes at each snap() call.  Non-mutating phases share a single DB
    seed; only the four admin-action screenshots need a reseed.

    Expected runtime: ~5 min.
    """

    # ── main test ──────────────────────────────────────────────────────

    def test_theme_showcase(
        self,
        page,
        frontend_server,
        backend_server,
        oidc_server,
        backend_db_path,
    ):
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        page.on("dialog", lambda d: d.accept())

        # ── one-time data seed ────────────────────────────────────────
        _reset_db(backend_db_path)
        _seed_showcase_data(backend_url, oidc_issuer, backend_db_path)
        _register_and_activate(
            backend_url, oidc_issuer, backend_db_path,
            sub="defunct-user", username="defunct_user",
            name="Defunct User", email="defunct@test.local",
        )
        _grant_claims(
            backend_db_path, "defunct_user",
            BASIC | MEALBOT | HAPPY_HOUR,
        )
        _set_status(backend_db_path, "defunct_user", "defunct")

        # ── cache session cookies for every role ──────────────────────
        admin_cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="dev-admin", name="Admin", email="admin@dev.local",
        )
        alice_cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="user-alice", name="Alice Chen",
            email="alice@example.com",
        )
        defunct_cookies = _oidc_login_cookies(
            backend_url, oidc_issuer,
            sub="defunct-user", name="Defunct User",
            email="defunct@test.local",
        )

        flow = FlowRecorder("12_theme_showcase")
        snap = flow.snap

        # ╔══════════════════════════════════════════════════════════════
        # ║ Phase 1 — Unauthenticated (3 page-states)
        # ╚══════════════════════════════════════════════════════════════
        _clear_user(page)

        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        time.sleep(0.3)
        snap(page, "login_page")

        page.goto(
            f"{frontend_url}/login?error=Authentication+failed"
        )
        page.wait_for_load_state("networkidle")
        snap(page, "login_error")

        page.goto(f"{frontend_url}/nonexistent-page")
        page.wait_for_load_state("networkidle")
        snap(page, "page_404")

        # ╔══════════════════════════════════════════════════════════════
        # ║ Phase 2 — Admin session, data-rich pages (10 page-states)
        # ╚══════════════════════════════════════════════════════════════
        _inject_cookies(page, admin_cookies, frontend_url)

        # Happy hour — three scroll positions
        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.15)
        snap(page, "happyhour_top")

        page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight / 2)"
        )
        time.sleep(0.15)
        snap(page, "happyhour_mid")

        page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )
        time.sleep(0.15)
        snap(page, "happyhour_bottom")

        # Mealbot — two scroll positions
        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.15)
        snap(page, "mealbot_top")

        page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )
        time.sleep(0.15)
        snap(page, "mealbot_bottom")

        # Account — two scroll positions
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.15)
        snap(page, "account_top")

        page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )
        time.sleep(0.15)
        snap(page, "account_bottom")

        # Admin — three tabs
        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "admin_pending_tab")

        tab = page.locator(".admin-tab[data-tab='accounts']")
        if tab.count() > 0:
            tab.click()
            time.sleep(0.3)
        snap(page, "admin_accounts_tab")

        tab = page.locator(".admin-tab[data-tab='claims']")
        if tab.count() > 0:
            tab.click()
            time.sleep(0.3)
        snap(page, "admin_claims_tab")

        # ╔══════════════════════════════════════════════════════════════
        # ║ Phase 3 — Regular-user perspective (3 page-states)
        # ╚══════════════════════════════════════════════════════════════
        _clear_user(page)
        _inject_cookies(page, alice_cookies, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "user_account")

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "user_happyhour")

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "user_mealbot")

        # ╔══════════════════════════════════════════════════════════════
        # ║ Phase 4 — Defunct user / read-only (3 page-states)
        # ╚══════════════════════════════════════════════════════════════
        _clear_user(page)
        _inject_cookies(page, defunct_cookies, frontend_url)

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "defunct_account")

        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "defunct_happyhour")

        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        snap(page, "defunct_mealbot")

        # ╔══════════════════════════════════════════════════════════════
        # ║ Phase 5 — Mobile views, admin session (10 page-states)
        # ╚══════════════════════════════════════════════════════════════
        _clear_user(page)
        _inject_cookies(page, admin_cookies, frontend_url)
        page.set_viewport_size({"width": 375, "height": 812})

        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        time.sleep(0.3)
        snap(page, "mobile_login")

        toggle = page.query_selector("#menu-toggle")
        if toggle and toggle.is_visible():
            toggle.click()
            time.sleep(0.3)
            snap(page, "mobile_login_sidebar")
            page.evaluate(
                "document.getElementById('sidebar')"
                ".classList.remove('open');"
                "document.getElementById('sidebar-overlay')"
                ".classList.remove('open');"
            )
            time.sleep(0.1)

        for path, name in [
            ("/happyhour", "mobile_happyhour"),
            ("/mealbot", "mobile_mealbot"),
            ("/account", "mobile_account"),
            ("/admin", "mobile_admin"),
        ]:
            page.goto(f"{frontend_url}{path}")
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)
            snap(page, name)

            toggle = page.query_selector("#menu-toggle")
            if toggle and toggle.is_visible():
                toggle.click()
                time.sleep(0.3)
                snap(page, f"{name}_sidebar")
                page.evaluate(
                    "document.getElementById('sidebar')"
                    ".classList.remove('open');"
                    "document.getElementById('sidebar-overlay')"
                    ".classList.remove('open');"
                )
                time.sleep(0.1)

        # Restore desktop viewport for remaining phases
        page.set_viewport_size({"width": 1280, "height": 720})

        # ╔══════════════════════════════════════════════════════════════
        # ║ Phase 6 — Admin actions / mutating  (4 page-states)
        # ║ Each action changes server state so we reseed before it,
        # ║ then snap all 23 themes on the result page.
        # ╚══════════════════════════════════════════════════════════════

        def _reseed_and_login():
            """Reset DB, re-seed data, inject admin cookies."""
            _reset_db(backend_db_path)
            _seed_showcase_data(backend_url, oidc_issuer, backend_db_path)
            _clear_user(page)
            _inject_cookies(page, admin_cookies, frontend_url)

        # Action 1 — approve pending account
        _reseed_and_login()
        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        tab = page.locator(".admin-tab[data-tab='pending']")
        if tab.count() > 0:
            tab.click()
            time.sleep(0.3)
        btn = page.locator(".approve-account-btn").first
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            time.sleep(0.5)
        snap(page, "admin_after_approve")

        # Action 2 — approve pending claim
        _reseed_and_login()
        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        tab = page.locator(".admin-tab[data-tab='claims']")
        if tab.count() > 0:
            tab.click()
            time.sleep(0.3)
        btn = page.locator(".approve-claim-btn").first
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            time.sleep(0.5)
        snap(page, "admin_after_claim_approve")

        # Action 3 — cancel upcoming happy-hour event
        _reseed_and_login()
        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        btn = page.locator(".cancel-event-btn").first
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            time.sleep(0.8)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.15)
        snap(page, "happyhour_after_cancel")

        # Action 4 — void a mealbot record
        _reseed_and_login()
        page.goto(f"{frontend_url}/mealbot")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        btn = page.locator(".void-record-btn").first
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            time.sleep(0.8)
        snap(page, "mealbot_after_void")
