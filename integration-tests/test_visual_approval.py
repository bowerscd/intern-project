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
    """Walk through every user-facing workflow and capture screenshots."""

    def test_01_public_pages(
        self,
        page,
        frontend_server,
        request,
    ):
        """Screenshot all publicly accessible pages."""
        frontend_url, _ = frontend_server

        # Home / index
        page.goto(f"{frontend_url}/")
        page.wait_for_load_state("networkidle")
        _snap(page, "index_page", request)

        # Login page
        page.goto(f"{frontend_url}/login")
        page.wait_for_load_state("networkidle")
        _snap(page, "login_page", request)

        # Happy Hour (public view, unauthenticated)
        page.goto(f"{frontend_url}/happyhour")
        page.wait_for_load_state("networkidle")
        _snap(page, "happyhour_public", request)

    def test_02_registration_flow(
        self,
        page,
        frontend_server,
        backend_server,
        oidc_server,
        backend_db_path,
        request,
    ):
        """Screenshot the full OIDC registration workflow."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Start at registration page
        page.goto(f"{frontend_url}/auth/complete-registration")
        page.wait_for_load_state("networkidle")
        _snap(page, "registration_page_initial", request)

        # Register via OIDC using direct backend API (then screenshot results)
        sub = "visual-test-user"
        name = "Visual Tester"
        email = "visual@test.local"

        client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
        resp = client.get("/api/v2/auth/register/test")
        assert resp.status_code in (302, 307)
        authorize_url = resp.headers["location"]
        authorize_url = rewrite_oidc_url(authorize_url, oidc_issuer)

        # Follow OIDC
        resp = httpx.get(authorize_url, follow_redirects=False, timeout=10)
        parsed = urlparse(authorize_url)
        qs = parse_qs(parsed.query)
        approve_url = f"{oidc_issuer}/authorize/approve?" + urlencode({
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub,
            "name": name,
            "email": email,
        })
        resp = httpx.get(approve_url, follow_redirects=False, timeout=10)
        callback_url = resp.headers["location"]
        cb = urlparse(callback_url)
        resp = client.get(f"{cb.path}?{cb.query}")

        # Complete registration
        csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        resp = client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "visualtester"},
            headers={"X-CSRF-Token": csrf},
        )
        _snap(page, "registration_submitted", request)

        # Activate account
        activate_account(backend_db_path, "visualtester")

        # Login with the new account
        client2 = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
        resp = client2.get("/api/v2/auth/login/test")
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
        parsed2 = urlparse(auth_url)
        qs2 = parse_qs(parsed2.query)
        approve2 = f"{oidc_issuer}/authorize/approve?" + urlencode({
            "redirect_uri": qs2["redirect_uri"][0],
            "state": qs2["state"][0],
            "nonce": qs2["nonce"][0],
            "sub": sub, "name": name, "email": email,
        })
        resp = httpx.get(approve2, follow_redirects=False, timeout=10)
        cb2 = urlparse(resp.headers["location"])
        client2.get(f"{cb2.path}?{cb2.query}")

        # Transfer cookies to browser context
        for name_k, value in client2.cookies.items():
            page.context.add_cookies([{
                "name": name_k,
                "value": value,
                "url": frontend_url,
            }])

        client.close()
        client2.close()

        # Now screenshot authenticated pages
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "account_page_fresh", request)

    def test_03_account_features(
        self,
        page,
        frontend_server,
        backend_server,
        oidc_server,
        backend_db_path,
        request,
    ):
        """Screenshot the account page with various feature toggles."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Login as the admin dev user
        sub = "dev-admin"
        client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
        resp = client.get("/api/v2/auth/login/test")
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
        parsed = urlparse(auth_url)
        qs = parse_qs(parsed.query)
        approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub, "name": "Admin", "email": "admin@dev.local",
        })
        resp = httpx.get(approve, follow_redirects=False, timeout=10)
        cb = urlparse(resp.headers["location"])
        client.get(f"{cb.path}?{cb.query}")

        # Transfer cookies
        for name_k, value in client.cookies.items():
            page.context.add_cookies([{
                "name": name_k, "value": value, "url": frontend_url,
            }])
        client.close()

        # Account page
        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "admin_account_page", request)

        # Admin dashboard
        page.goto(f"{frontend_url}/admin")
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        _snap(page, "admin_dashboard_pending", request)

        # Click "All Accounts" tab
        tabs = page.query_selector_all(".admin-tab")
        if len(tabs) > 1:
            tabs[1].click()
            time.sleep(1)
            _snap(page, "admin_dashboard_accounts", request)

        # Click "Claim Requests" tab
        if len(tabs) > 2:
            tabs[2].click()
            time.sleep(1)
            _snap(page, "admin_dashboard_claims", request)

    def test_04_theme_showcase(
        self,
        page,
        frontend_server,
        backend_server,
        oidc_server,
        request,
    ):
        """Screenshot several themes applied to the account page."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Login as admin
        sub = "dev-admin"
        client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
        resp = client.get("/api/v2/auth/login/test")
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
        parsed = urlparse(auth_url)
        qs = parse_qs(parsed.query)
        approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub, "name": "Admin", "email": "admin@dev.local",
        })
        resp = httpx.get(approve, follow_redirects=False, timeout=10)
        cb = urlparse(resp.headers["location"])
        client.get(f"{cb.path}?{cb.query}")

        for k, v in client.cookies.items():
            page.context.add_cookies([{"name": k, "value": v, "url": frontend_url}])
        client.close()

        themes_to_screenshot = [
            "default", "light", "dracula", "nord", "cyberpunk",
            "retro-terminal", "cherry-blossom", "ocean", "neon",
            "paper", "high-contrast", "coffee", "emerald",
        ]

        for theme in themes_to_screenshot:
            page.goto(f"{frontend_url}/account")
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)
            # Apply theme via JS
            if theme == "default":
                page.evaluate("document.documentElement.removeAttribute('data-theme')")
            else:
                page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
            time.sleep(0.3)
            _snap(page, f"theme_{theme}", request)

    def test_05_defunct_account_view(
        self,
        page,
        frontend_server,
        backend_server,
        oidc_server,
        backend_db_path,
        request,
    ):
        """Screenshot what a defunct (disabled) account sees."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create and disable a test user
        sub = "defunct-test-user"
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
            "sub": sub, "name": "Defunct User", "email": "defunct@test.local",
        })
        resp = httpx.get(approve, follow_redirects=False, timeout=10)
        cb = urlparse(resp.headers["location"])
        client.get(f"{cb.path}?{cb.query}")

        csrf = client.get("/api/v2/auth/csrf-token").json()["csrf_token"]
        client.post(
            "/api/v2/auth/complete-registration",
            json={"username": "defunctuser"},
            headers={"X-CSRF-Token": csrf},
        )
        client.close()

        # Activate then set to defunct
        activate_account(backend_db_path, "defunctuser")
        conn = sqlite3.connect(backend_db_path)
        conn.execute("UPDATE accounts SET status = 'defunct' WHERE username = 'defunctuser'")
        conn.commit()
        conn.close()

        # Login as defunct user
        client2 = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
        resp = client2.get("/api/v2/auth/login/test")
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
        parsed = urlparse(auth_url)
        qs = parse_qs(parsed.query)
        approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub, "name": "Defunct User", "email": "defunct@test.local",
        })
        resp = httpx.get(approve, follow_redirects=False, timeout=10)
        cb = urlparse(resp.headers["location"])
        client2.get(f"{cb.path}?{cb.query}")

        for k, v in client2.cookies.items():
            page.context.add_cookies([{"name": k, "value": v, "url": frontend_url}])
        client2.close()

        page.goto(f"{frontend_url}/account")
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        _snap(page, "defunct_account_view", request)

    def test_06_mobile_views(
        self,
        browser,
        frontend_server,
        backend_server,
        oidc_server,
        request,
    ):
        """Screenshot pages at mobile viewport width."""
        frontend_url, _ = frontend_server
        backend_url, _ = backend_server
        oidc_issuer, _ = oidc_server

        # Create a mobile-sized context
        context = browser.new_context(
            base_url=frontend_url,
            viewport={"width": 375, "height": 812},
            is_mobile=True,
        )
        mob_page = context.new_page()

        # Login as admin
        sub = "dev-admin"
        client = httpx.Client(base_url=backend_url, follow_redirects=False, timeout=10)
        resp = client.get("/api/v2/auth/login/test")
        auth_url = rewrite_oidc_url(resp.headers["location"], oidc_issuer)
        resp = httpx.get(auth_url, follow_redirects=False, timeout=10)
        parsed = urlparse(auth_url)
        qs = parse_qs(parsed.query)
        approve = f"{oidc_issuer}/authorize/approve?" + urlencode({
            "redirect_uri": qs["redirect_uri"][0],
            "state": qs["state"][0],
            "nonce": qs["nonce"][0],
            "sub": sub, "name": "Admin", "email": "admin@dev.local",
        })
        resp = httpx.get(approve, follow_redirects=False, timeout=10)
        cb = urlparse(resp.headers["location"])
        client.get(f"{cb.path}?{cb.query}")

        for k, v in client.cookies.items():
            context.add_cookies([{"name": k, "value": v, "url": frontend_url}])
        client.close()

        pages_to_shot = [
            ("/", "mobile_index"),
            ("/login", "mobile_login"),
            ("/account", "mobile_account"),
            ("/admin", "mobile_admin"),
            ("/happyhour", "mobile_happyhour"),
        ]

        for path, name in pages_to_shot:
            mob_page.goto(f"{frontend_url}{path}")
            mob_page.wait_for_load_state("networkidle")
            time.sleep(1)
            _snap(mob_page, name, request)

            # Open sidebar on mobile
            toggle = mob_page.query_selector("#menu-toggle")
            if toggle and toggle.is_visible():
                toggle.click()
                time.sleep(0.5)
                _snap(mob_page, f"{name}_sidebar_open", request)
                # Close sidebar
                overlay = mob_page.query_selector("#sidebar-overlay")
                if overlay and overlay.is_visible():
                    overlay.click()
                    time.sleep(0.3)

        mob_page.close()
        context.close()
