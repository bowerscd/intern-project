"""Frontend server configuration — hostname, API base URL, session cookie name."""

import os
from config import SERVER_HOSTNAME, BACKEND_HOSTNAME, USE_MOCK, USE_PROXY


def hostname() -> str:
    """Return the configured server hostname.

    :returns: The server hostname string (e.g., OS hostname or env override).
    :rtype: str
    """
    return SERVER_HOSTNAME


def api_base() -> str:
    """Return the API base URL for client-side fetch requests.

    - Mock mode: return backend URL (mocks intercept anyway)
    - Proxy mode: return "" (same-origin, Flask proxies to backend)
    - Direct mode: return backend URL (browser calls backend directly)

    :returns: The API base URL string.
    :rtype: str
    """
    if USE_MOCK:
        return backend_url()
    elif USE_PROXY:
        return ""
    else:
        return backend_url()


def backend_url() -> str:
    """Return the internal backend URL for server-side proxy requests.

    Respects API_BASE env var if set (for tests), otherwise uses
    Docker internal DNS with configurable port (default 80).

    :returns: The backend URL string.
    :rtype: str
    """
    # Allow explicit override via API_BASE (used in integration tests)
    api_base_override = os.environ.get("API_BASE")
    if api_base_override:
        return api_base_override

    port = os.environ.get("BACKEND_PORT", "80")
    return f"http://{BACKEND_HOSTNAME}:{port}"


def session_cookie_name() -> str:
    """Return the session cookie name (must match backend).

    Format: "{hostname}.session"
    Examples:
      - "localhost.session" (dev)
      - "beta.bowerscd.xyz.session" (prod)

    :returns: The session cookie name string.
    :rtype: str
    """
    return f"{hostname()}.session"
