"""Server configuration — hostname, scheme, and dev-mode detection."""

from config import DEV_MODE, SERVER_HOSTNAME

if DEV_MODE:
    __SCHEME = "http"
else:
    __SCHEME = "https"

__HOSTNAME = SERVER_HOSTNAME


def hostname() -> str:
    """Return the configured server hostname.

    :returns: The server hostname string.
    :rtype: str
    """
    return __HOSTNAME


def api_server() -> str:
    """Return the full API server base URL.

    :returns: A URL string of the form ``{scheme}://api.{hostname}``.
    :rtype: str
    """
    return f"{__SCHEME}://api.{__HOSTNAME}"
