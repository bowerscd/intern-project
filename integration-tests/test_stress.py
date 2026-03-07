"""Stress tests using Locust for load testing the backend API.

This file is NOT a pytest test module — it uses the Locust framework.
The ``conftest_`` prefix is avoided so pytest does not auto-collect it.

Usage:
    # Run from the integration-tests directory:
    locust -f test_stress.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:8000

    # Or via the root Makefile:
    make test-stress

    # Interactive web UI:
    locust -f test_stress.py --host http://127.0.0.1:8000
    # Then open http://localhost:8089
"""

from __future__ import annotations

# Guard against pytest collection — this file requires locust which is
# an optional dependency used only for load testing, not for CI.
try:
    from locust import HttpUser, between, task, events, tag  # noqa: F401
except ImportError:
    import sys

    if "pytest" in sys.modules:
        # Being collected by pytest without locust installed — skip gracefully
        import pytest

        pytest.skip("locust not installed", allow_module_level=True)
    raise

import random
import string


def _random_username(prefix: str = "stress") -> str:
    """Generate a random username for stress testing."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{prefix}_{suffix}"


class HealthCheckUser(HttpUser):
    """Lightweight user that hammers health/status endpoints."""

    wait_time = between(0.1, 0.5)
    weight = 3

    @task(10)
    @tag("health")
    def healthz(self):
        self.client.get("/healthz")

    @task(2)
    @tag("health")
    def openapi_schema(self):
        self.client.get("/openapi.json")

    @task(1)
    @tag("health")
    def docs(self):
        self.client.get("/docs")


class UnauthenticatedUser(HttpUser):
    """User that hits public endpoints without authentication."""

    wait_time = between(0.5, 2.0)
    weight = 2

    @task(5)
    @tag("public")
    def healthz(self):
        self.client.get("/healthz")

    @task(3)
    @tag("public")
    def list_phone_providers(self):
        """This should return 401 for unauthenticated users."""
        with self.client.get(
            "/api/v2/account/phone-providers",
            catch_response=True,
        ) as response:
            # Accept both 200 (if no auth needed) and 401/403
            if response.status_code in (200, 401, 403):
                response.success()

    @task(2)
    @tag("public")
    def list_themes(self):
        """Public endpoint for theme names."""
        self.client.get("/api/v2/account/themes")

    @task(1)
    @tag("public")
    def attempt_unauthenticated_profile(self):
        """Should receive 401."""
        with self.client.get(
            "/api/v2/account/profile",
            catch_response=True,
        ) as response:
            if response.status_code in (401, 403):
                response.success()

    @task(1)
    @tag("public")
    def attempt_unauthenticated_ledger(self):
        """Should receive 401."""
        with self.client.get(
            "/api/v2/mealbot/ledger",
            catch_response=True,
        ) as response:
            if response.status_code in (401, 403):
                response.success()


class AuthenticatedReadUser(HttpUser):
    """Simulates an authenticated user performing read-only actions.

    Expects a pre-existing session cookie. In practice, set up the dev
    environment first (``make dev``) and grab a session cookie from a
    browser.

    Set the session cookie via the ``STRESS_SESSION_COOKIE`` env var or
    rely on the dev admin (which is auto-seeded).
    """

    wait_time = between(1.0, 3.0)
    weight = 5

    def on_start(self):
        """Login via the mock OIDC provider to obtain a session."""
        import os

        cookie = os.environ.get("STRESS_SESSION_COOKIE")
        if cookie:
            self.client.cookies.set("mealbot_session", cookie)
            return

        # Try login via mock OIDC (dev mode)
        try:
            resp = self.client.get(
                "/api/v2/auth/login/test",
                allow_redirects=False,
            )
            if resp.status_code in (302, 307):
                oidc_url = resp.headers.get("location", "")
                if oidc_url and "authorize" in oidc_url:
                    from urllib.parse import urlparse, parse_qs, urlencode

                    parsed = urlparse(oidc_url)
                    qs = parse_qs(parsed.query)
                    oidc_base = f"{parsed.scheme}://{parsed.netloc}"
                    approve_url = f"{oidc_base}/authorize/approve?" + urlencode({
                        "redirect_uri": qs.get("redirect_uri", [""])[0],
                        "state": qs.get("state", [""])[0],
                        "nonce": qs.get("nonce", [""])[0],
                        "sub": "dev-admin",
                        "name": "Admin",
                        "email": "admin@dev.local",
                    })
                    import requests
                    oidc_resp = requests.get(approve_url, allow_redirects=False, timeout=5)
                    if oidc_resp.status_code == 302:
                        callback = oidc_resp.headers["location"]
                        cb_parsed = urlparse(callback)
                        self.client.get(
                            f"{cb_parsed.path}?{cb_parsed.query}",
                            allow_redirects=False,
                        )
        except Exception:
            pass

    @task(10)
    @tag("read")
    def get_profile(self):
        with self.client.get(
            "/api/v2/account/profile",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(5)
    @tag("read")
    def get_mealbot_ledger(self):
        with self.client.get(
            "/api/v2/mealbot/ledger?page=1&page_size=20",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(5)
    @tag("read")
    def get_mealbot_my_ledger(self):
        with self.client.get(
            "/api/v2/mealbot/ledger/me?page=1&page_size=20",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(3)
    @tag("read")
    def get_mealbot_summary(self):
        with self.client.get(
            "/api/v2/mealbot/summary",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(5)
    @tag("read")
    def get_happyhour_events(self):
        with self.client.get(
            "/api/v2/happyhour/events?page=1&page_size=20",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(3)
    @tag("read")
    def get_happyhour_upcoming(self):
        with self.client.get(
            "/api/v2/happyhour/events/upcoming",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(3)
    @tag("read")
    def get_happyhour_rotation(self):
        with self.client.get(
            "/api/v2/happyhour/rotation",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(3)
    @tag("read")
    def get_happyhour_locations(self):
        with self.client.get(
            "/api/v2/happyhour/locations?page=1&page_size=50",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(2)
    @tag("read")
    def get_admin_accounts(self):
        with self.client.get(
            "/api/v2/account/admin/accounts",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(2)
    @tag("read")
    def get_admin_claims(self):
        with self.client.get(
            "/api/v2/account/admin/claims",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()

    @task(1)
    @tag("read")
    def get_themes(self):
        self.client.get("/api/v2/account/themes")

    @task(1)
    @tag("read")
    def get_phone_providers(self):
        with self.client.get(
            "/api/v2/account/phone-providers",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()


class BurstUser(HttpUser):
    """Simulates burst traffic — rapid sequential requests."""

    wait_time = between(0.05, 0.2)
    weight = 1

    @task
    @tag("burst")
    def rapid_health_checks(self):
        for _ in range(10):
            self.client.get("/healthz")

    @task
    @tag("burst")
    def rapid_auth_attempts(self):
        """Rapid 401s to test rate limiting behavior."""
        for _ in range(5):
            with self.client.get(
                "/api/v2/account/profile",
                catch_response=True,
            ) as response:
                if response.status_code in (200, 401, 403, 429):
                    response.success()
