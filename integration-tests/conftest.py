"""Shared fixtures that start/stop the mock OIDC, backend, and frontend servers.

There are two modes of operation:

**Local mode** (default / ``make test-local``):
  All three services are spawned as child processes on dynamic localhost
  ports.

**External mode** (``make test`` with Docker Compose, or CI):
  Set ``BACKEND_URL`` and ``FRONTEND_URL`` environment variables to point
  at already-running services.  The fixtures will reuse those URLs instead
  of spawning processes.  A local mock-OIDC is still started for tests
  that contact it directly; the Docker stack has its own OIDC container
  used by the backend.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Generator

import httpx
import pytest

from mock_oidc import start_server as start_oidc, stop_server as stop_oidc

# ---------------------------------------------------------------------------
# Playwright availability check — gracefully degrade when not installed
# ---------------------------------------------------------------------------

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

# ---------------------------------------------------------------------------
# Environment overrides — set by Docker Compose / CI to skip process spawning
# ---------------------------------------------------------------------------

_EXTERNAL_BACKEND_URL = os.environ.get("BACKEND_URL")     # e.g. http://localhost:8000
_EXTERNAL_FRONTEND_URL = os.environ.get("FRONTEND_URL")    # e.g. http://localhost:5000

# ---------------------------------------------------------------------------
# Workspace paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent
_WORKSPACE = _ROOT.parent
_BACKEND_DIR = _WORKSPACE / "backend"
_FRONTEND_DIR = _WORKSPACE / "frontend"


def _find_venv_python(project_dir: Path) -> str:
    """Locate the Python interpreter for *project_dir*.

    Search order:
      1. ``<project_dir>/.venv/bin/python``  (per-project venv)
      2. ``<workspace>/.venv/bin/python``    (shared workspace venv)
      3. ``sys.executable``                  (current interpreter)
    """
    for candidate in (
        project_dir / ".venv" / "bin" / "python",
        _WORKSPACE / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    """Block until *port* accepts connections or *timeout* expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"Port {port} did not open within {timeout}s")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _db_path(tmp_path_factory):
    """Create a temp file path for the backend's file-based SQLite database.

    Using a file (rather than in-memory) lets integration tests that need
    direct DB access (e.g. granting admin claims) connect to the same
    database the backend subprocess uses.
    """
    db_dir = tmp_path_factory.mktemp("backend_db")
    return str(db_dir / "mealbot.db")


@pytest.fixture(scope="session")
def oidc_server():
    """Start the mock OIDC provider and yield its (issuer_url, port).

    In external (Docker) mode the OIDC container is already running and
    its port 9000 is published to the host, so we skip starting a local
    instance and return the host-reachable URL instead.
    """
    if _EXTERNAL_BACKEND_URL:
        yield "http://127.0.0.1:9000", 9000
        return
    server, issuer_url, port = start_oidc(port=0)
    yield issuer_url, port
    stop_oidc(server)


@pytest.fixture(scope="session")
def backend_server(oidc_server, _db_path):
    """Start the FastAPI backend, or reuse ``BACKEND_URL`` if set.

    Yields ``(base_url, port)``.
    """
    if _EXTERNAL_BACKEND_URL:
        from urllib.parse import urlparse
        port = urlparse(_EXTERNAL_BACKEND_URL).port or 8000
        yield _EXTERNAL_BACKEND_URL, port
        return

    oidc_issuer, _ = oidc_server
    port = _free_port()
    callback_url = f"http://127.0.0.1:{port}/api/v2/auth/callback/test"

    env = {
        **os.environ,
        "DEV": "1",
            "SERVER_HOSTNAME": "localhost",
        "TEST_OIDC_ISSUER": oidc_issuer,
        "TEST_CLIENT_ID": "client_id1",
        "TEST_CLIENT_SECRET": "definitely_a_secret",
        "TEST_REDIRECT_URI": callback_url,
        "DATABASE_URI": f"sqlite:///{_db_path}",
        "RATELIMIT_ENABLED": "false",
        # Google provider vars (required for import, won't be used)
        "GOOGLE_REDIRECT_URI": "http://unused",
        "GOOGLE_CLIENT_SECRET": "unused",
        "GOOGLE_CLIENT_ID": "unused",
    }

    backend_python = _find_venv_python(_BACKEND_DIR)

    proc = subprocess.Popen(
        [
            backend_python, "-m", "uvicorn",
            "app:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=str(_BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _wait_for_port(port)
    except TimeoutError:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Backend failed to start on port {port}.\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    base_url = f"http://127.0.0.1:{port}"
    yield base_url, port

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def frontend_server(backend_server):
    """Start the Flask frontend, or reuse ``FRONTEND_URL`` if set.

    Yields ``(base_url, port)``.
    """
    if _EXTERNAL_FRONTEND_URL:
        from urllib.parse import urlparse
        port = urlparse(_EXTERNAL_FRONTEND_URL).port or 5000
        yield _EXTERNAL_FRONTEND_URL, port
        return

    # ── Build the TypeScript sources so static/dist/ is up-to-date ──
    # Without this, stale compiled JS can cause hard-to-diagnose test
    # failures (e.g. missing CSRF handling that only exists in the TS
    # source but not in the compiled output).
    _tsc = _FRONTEND_DIR / "node_modules" / ".bin" / "tsc"
    if _tsc.exists():
        result = subprocess.run(
            [str(_tsc), "-p", "tsconfig.json"],
            cwd=str(_FRONTEND_DIR),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            import warnings
            warnings.warn(
                f"TypeScript build had errors (non-fatal):\n"
                f"{result.stderr.decode()[:500]}",
                stacklevel=2,
            )

    backend_url, _ = backend_server
    port = _free_port()

    env = {
        **os.environ,
        "API_BASE": backend_url,
        "USE_MOCK": "false",
        "USE_PROXY": "true",
        "DEV": "1",
            "SERVER_HOSTNAME": "localhost",
        "FLASK_RUN_PORT": str(port),
    }

    frontend_python = _find_venv_python(_FRONTEND_DIR)

    proc = subprocess.Popen(
        [
            frontend_python, "-m", "flask",
            "--app", "app",
            "run",
            "--host", "127.0.0.1",
            "--port", str(port),
        ],
        cwd=str(_FRONTEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _wait_for_port(port)
    except TimeoutError:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Frontend failed to start on port {port}.\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    base_url = f"http://127.0.0.1:{port}"
    yield base_url, port

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def backend_db_path(_db_path, backend_server) -> str:
    """Path to the backend's SQLite database file.

    Depends on *backend_server* to ensure the subprocess (and its DB)
    has been initialised before any test tries to open the file.

    In Docker mode the DB is exposed via a bind mount; its host-side path
    is passed in via the ``BACKEND_DB_PATH`` env var.  If that env var is
    absent the test is skipped (old behaviour, kept as a safety net).
    """
    if _EXTERNAL_BACKEND_URL:
        env_path = os.environ.get("BACKEND_DB_PATH")
        if env_path:
            return env_path
        pytest.skip("Direct DB access unavailable: set BACKEND_DB_PATH to the mounted DB file")
    return _db_path


@pytest.fixture(scope="session")
def client(backend_server) -> Generator[httpx.Client, None, None]:
    """An httpx client pointed at the backend."""
    base_url, _ = backend_server
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="session")
def frontend_client(frontend_server) -> Generator[httpx.Client, None, None]:
    """An httpx client pointed at the frontend."""
    base_url, _ = frontend_server
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0) as c:
        yield c


# ---------------------------------------------------------------------------
# Playwright browser fixtures
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Register the ``browser`` marker so that Playwright tests can be
    selectively included or excluded (``-m browser`` / ``-m 'not browser'``).
    """
    config.addinivalue_line(
        "markers",
        "browser: marks tests that require a real browser via Playwright",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip ``@pytest.mark.browser`` tests when Playwright is not installed."""
    if _HAS_PLAYWRIGHT:
        return
    skip_pw = pytest.mark.skip(reason="Playwright is not installed — run `pip install playwright && playwright install --with-deps chromium`")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip_pw)


@pytest.fixture(scope="session")
def _playwright_instance():
    """Start a single Playwright instance for the test session."""
    if not _HAS_PLAYWRIGHT:
        pytest.skip("Playwright is not installed")
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture(scope="session")
def browser(_playwright_instance):
    """Launch a headless Chromium browser for the test session."""
    browser = _playwright_instance.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture()
def browser_context(browser, frontend_server):
    """Create a fresh, isolated browser context for each test.

    Sets the base URL so ``page.goto("/some-path")`` works.
    """
    frontend_url, _ = frontend_server
    context = browser.new_context(base_url=frontend_url)
    yield context
    context.close()


@pytest.fixture()
def page(browser_context):
    """Create a fresh page within the per-test browser context."""
    page = browser_context.new_page()
    yield page
    page.close()
