"""Tests for the server module and app-level configuration."""


class TestServerModule:
    """Cover server module branches."""

    def test_dev_mode_hostname(self) -> None:
        """Verify :func:`hostname` returns ``localhost`` in dev mode."""
        from server import hostname
        h = hostname()
        assert h == "localhost"

    def test_dev_mode_api_server(self) -> None:
        """Verify :func:`api_server` returns an HTTP localhost URL in dev mode."""
        from server import api_server
        from config import DEV_MODE
        if DEV_MODE:
            s = api_server()
            assert s.startswith("http://")
            assert "api.localhost" in s


class TestCorsConfig:
    """
    CORS origins are now driven by ``config.CORS_ALLOW_ORIGINS``.
    In dev mode the default is ``["*"]``; in production it's ``[]``.
    """

    def test_dev_cors_default_is_wildcard(self) -> None:
        """In dev mode the default CORS origins list is ``['*']``."""
        from config import DEV_MODE, CORS_ALLOW_ORIGINS
        if DEV_MODE:
            assert CORS_ALLOW_ORIGINS == ["*"]


class TestSessionSecret:
    """
    The session secret is now read from ``config.SESSION_SECRET`` which
    persists across restarts via ``settings.json``.
    """

    def test_dev_secret_is_deterministic(self) -> None:
        """In dev mode the secret is the static value from settings.json."""
        from app import secret
        assert secret == "dev-only-not-for-production"
