"""Centralised application configuration.

Loads settings from ``settings.json`` (if present) with environment-variable
fallbacks.  Every other module should read configuration through the
attributes exposed here rather than reaching into ``os.environ`` directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Optional

_SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"

_settings: dict[str, Any] = {}


def _load_settings() -> dict[str, Any]:
    """Read and cache the on-disk settings file.

    :returns: Parsed settings dictionary (empty if the file is missing).
    :rtype: dict[str, Any]
    """
    global _settings
    if not _settings and _SETTINGS_PATH.is_file():
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            _settings = json.load(fh)
    return _settings


def _get(key: str, env_var: str | None = None, default: Any = None) -> Any:
    """Return a config value from *settings.json* → env var → default.

    :param key: The JSON key to look up.
    :param env_var: Optional environment variable name to try as fallback.
    :param default: Value returned when neither source provides one.
    :returns: The resolved configuration value.
    """
    s = _load_settings()
    val = s.get(key)
    if val is not None:
        return val
    if env_var is not None:
        env_val = os.environ.get(env_var)
        if env_val is not None:
            return env_val
    return default


def _get_json(key: str, env_var: str | None = None, default: Any = None) -> Any:
    """Like :func:`_get` but JSON-decode the environment variable.

    Useful for configuration values that are lists or dicts (e.g.
    ``CORS_ALLOW_ORIGINS='["https://example.com"]'``).

    :param key: The JSON key to look up in *settings.json*.
    :param env_var: Environment variable name whose value will be
        parsed as JSON.
    :param default: Fallback when neither source provides a value.
    :returns: The resolved configuration value.
    """
    s = _load_settings()
    val = s.get(key)
    if val is not None:
        return val
    if env_var is not None:
        env_val = os.environ.get(env_var)
        if env_val is not None:
            try:
                return json.loads(env_val)
            except (json.JSONDecodeError, TypeError):
                return env_val
    return default


# ---------------------------------------------------------------------------
# Public configuration attributes
# ---------------------------------------------------------------------------

DEV_MODE: bool = _get("dev_mode", "DEV", False) in (True, "1")
"""Whether the application is running in development mode."""

SERVER_HOSTNAME: str = _get("server_hostname", "SERVER_HOSTNAME", "localhost")
"""The public-facing server hostname."""

SESSION_SECRET: str = _get("session_secret", "SESSION_SECRET", None)  # type: ignore[assignment]
"""Secret key used for session cookie signing.

Must be set explicitly — there is no safe default for production.
If *dev_mode* is ``true`` the default in ``settings.json`` is ``"1234"``.
"""

DATABASE_URI: Optional[str] = _get("database_uri", "DATABASE_URI", None)
"""SQLAlchemy connection URI.  ``None`` → ephemeral in-memory SQLite."""

CORS_ALLOW_ORIGINS: List[str] = _get_json("cors_allow_origins", "CORS_ALLOW_ORIGINS", ["*"] if DEV_MODE else [])
"""Origins permitted by the CORS middleware."""

SESSION_COOKIE_DOMAIN: Optional[str] = _get("session_cookie_domain", "SESSION_COOKIE_DOMAIN", None)
"""Domain attribute for the session cookie.

Set to ``".yourdomain.com"`` in production so the cookie is shared across
subdomains (``api.``, ``mealbot.``, ``happyhour.``, etc.).
``None`` (default) confines the cookie to the exact serving origin.
"""

SESSION_SAME_SITE: str = _get("session_same_site", "SESSION_SAME_SITE", "lax")
"""``SameSite`` attribute for the session cookie.

Use ``"lax"`` (default) so the cookie survives the OIDC redirect from
Google back to the application.  ``"strict"`` is too restrictive for
OIDC flows that originate from a third-party domain.
"""

AUTH_REDIRECT_ORIGINS: List[str] = _get("auth_redirect_origins", None, [])
"""Origins allowed as absolute redirect targets after OIDC authentication.

In production, set this to the frontend origins that initiate login
via the API (e.g. ``["https://mealbot.yourdomain.com",
"https://happyhour.yourdomain.com"]``).  When a frontend passes an
absolute ``redirect`` parameter to ``/auth/login/{provider}``, its
origin must appear in this list.

Empty by default — only relative redirect paths are accepted.
"""

LOG_LEVEL: str = _get("log_level", "LOG_LEVEL", "INFO")
"""Python logging level name (e.g. ``"DEBUG"``, ``"INFO"``, ``"WARNING"``)."""

SCHEDULER_ENABLED: bool = _get("scheduler_enabled", "SCHEDULER_ENABLED", True) in (True, "1", "true")
"""Whether the APScheduler cron jobs should start on this instance.

In multi-instance deployments set ``SCHEDULER_ENABLED=0`` on all replicas
except one so that only a single process runs the periodic jobs.
"""


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def _validate_config() -> None:
    """Raise :class:`RuntimeError` when critical settings are missing.

    Only enforced when :pydata:`DEV_MODE` is ``False``.  Additionally,
    when a real ``DATABASE_URI`` is configured the validator warns if
    ``DEV_MODE`` is still enabled — a likely misconfiguration.
    """
    if DEV_MODE:
        if DATABASE_URI is not None:
            import logging as _log
            _log.getLogger(__name__).critical(
                "DEV_MODE is enabled but DATABASE_URI is set — "
                "this looks like a production deployment with dev guards disabled. "
                "Set DEV=0 or remove dev_mode from settings.json."
            )
        return
    errors: List[str] = []
    if SESSION_SECRET is None:
        errors.append("SESSION_SECRET must be set in production")
    if DATABASE_URI is None:
        errors.append("DATABASE_URI must be set in production")
    if not CORS_ALLOW_ORIGINS:
        errors.append("CORS_ALLOW_ORIGINS must be non-empty in production")
    elif "*" in CORS_ALLOW_ORIGINS:
        errors.append("CORS_ALLOW_ORIGINS must not contain '*' in production")
    if errors:
        raise RuntimeError(
            "Production configuration errors:\n  • " + "\n  • ".join(errors)
        )


_validate_config()
