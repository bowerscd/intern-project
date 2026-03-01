"""Mail configuration helpers for SMTP and sender address resolution."""

from urllib.parse import urlparse, ParseResult
from typing import NamedTuple

__smtp_host_url: None | ParseResult = None
__sender_email: str | None = None


class Host(NamedTuple):
    """Parsed SMTP connection parameters."""

    Scheme: str
    Port: int
    Hostname: str
    Username: str
    Password: str


def smtp_server_mail(_from_subtype: str = '') -> str:
    """Return the configured sender email address.

    An optional *_from_subtype* is inserted before the ``@`` to create
    sub-addressed variants (e.g. ``user+subtype@example.com``).

    :param _from_subtype: An optional sub-address tag inserted before
        the ``@`` in the sender address.  Must contain only safe
        characters (alphanumeric, ``+``, ``-``, ``_``, ``.``).
    :returns: The formatted sender email address.
    :rtype: str
    :raises ValueError: If *_from_subtype* contains unsafe characters.
    """
    import re
    from os import environ

    global __sender_email

    if _from_subtype and not re.match(r'^[a-zA-Z0-9+_.\-]*$', _from_subtype):
        raise ValueError(f"Invalid _from_subtype: {_from_subtype!r}")

    if __sender_email is None:
        __sender_email = environ['MAIL_SENDER']

    return __sender_email.replace('@', f"{_from_subtype}@")


def smtp_cfg() -> Host:
    """Parse and return SMTP connection parameters from the ``SMTP_URI`` env var.

    The URI must use the ``smtp`` scheme and include port, hostname,
    username, and password components.

    :returns: A :class:`Host` named-tuple with the parsed SMTP settings.
    :rtype: Host
    :raises ValueError: If the URI is missing required components.
    """
    from os import environ

    global __smtp_host_url

    if __smtp_host_url is None:
        __smtp_host_url = urlparse(environ['SMTP_URI'])

    if __smtp_host_url.scheme.lower() != "smtp":
        raise ValueError(f"SMTP_URI scheme must be 'smtp', got '{__smtp_host_url.scheme}'")
    if __smtp_host_url.port is None:
        raise ValueError("SMTP_URI must include a port")
    if __smtp_host_url.hostname is None:
        raise ValueError("SMTP_URI must include a hostname")
    if __smtp_host_url.username is None:
        raise ValueError("SMTP_URI must include a username")
    if __smtp_host_url.password is None:
        raise ValueError("SMTP_URI must include a password")

    return Host(__smtp_host_url.scheme,
                __smtp_host_url.port,
                __smtp_host_url.hostname,
                __smtp_host_url.username,
                __smtp_host_url.password)
