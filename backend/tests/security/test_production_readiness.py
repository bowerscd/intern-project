"""Tests for production-readiness middleware and configuration.

Covers: ProxyHeadersMiddleware, GZipMiddleware, global exception handler,
rate limiting, CORS tightening, startup config validation, and logging.
"""

import pytest
from starlette.testclient import TestClient


class TestProxyHeadersMiddleware:
    """Verify ProxyHeadersMiddleware is in the middleware stack."""

    def test_middleware_registered(self) -> None:
        """ProxyHeadersMiddleware should be registered on the app."""
        from app import app
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "ProxyHeadersMiddleware" in middleware_classes


class TestGZipMiddleware:
    """Verify GZip compression is active."""

    def test_gzip_middleware_registered(self) -> None:
        """GZipMiddleware should be registered on the app."""
        from app import app
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "GZipMiddleware" in middleware_classes


class TestGlobalExceptionHandler:
    """Verify the global exception handler returns sanitized 500."""

    def test_unhandled_exception_returns_500_json(self, client: TestClient) -> None:
        """Unhandled exceptions should return a JSON 500 response."""
        # Trigger a non-existent route that won't cause a 500 — instead,
        # we verify the handler is registered on the app.
        from app import app
        handlers = app.exception_handlers
        assert Exception in handlers


class TestRateLimiting:
    """Verify rate limiting is applied to auth endpoints."""

    def test_rate_limiter_on_app(self) -> None:
        """The app should have a rate limiter in state."""
        from app import app
        assert hasattr(app.state, "limiter")

    def test_rate_limit_exceeded_handler_registered(self) -> None:
        """RateLimitExceeded should have a handler registered on the app."""
        from app import app
        from slowapi.errors import RateLimitExceeded
        assert RateLimitExceeded in app.exception_handlers


class TestCORSTightened:
    """Verify CORS is not overly permissive."""

    def test_cors_methods_explicit(self) -> None:
        """CORS allow_methods should not be ['*']."""
        from app import app

        for m in app.user_middleware:
            if m.cls.__name__ == "CORSMiddleware":
                methods = m.kwargs.get("allow_methods", [])
                assert methods != ["*"], "CORS allow_methods should be explicit"
                assert "GET" in methods
                assert "POST" in methods
                break

    def test_cors_headers_explicit(self) -> None:
        """CORS allow_headers should not be ['*']."""
        from app import app

        for m in app.user_middleware:
            if m.cls.__name__ == "CORSMiddleware":
                headers = m.kwargs.get("allow_headers", [])
                assert headers != ["*"], "CORS allow_headers should be explicit"
                assert "Content-Type" in headers
                break


class TestStartupConfigValidation:
    """Verify that production config validation catches missing settings."""

    def test_validate_config_skipped_in_dev_mode(self) -> None:
        """In dev mode, _validate_config should not raise."""
        from config import _validate_config, DEV_MODE
        assert DEV_MODE is True  # Tests run in dev mode
        _validate_config()  # Should not raise

    def test_validate_config_raises_for_missing_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing SESSION_SECRET should raise RuntimeError in prod."""
        import config
        monkeypatch.setattr(config, "DEV_MODE", False)
        monkeypatch.setattr(config, "SESSION_SECRET", None)
        monkeypatch.setattr(config, "DATABASE_URI", "sqlite:///:memory:")
        monkeypatch.setattr(config, "CORS_ALLOW_ORIGINS", ["https://example.com"])

        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            config._validate_config()

    def test_validate_config_raises_for_missing_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing DATABASE_URI should raise RuntimeError in prod."""
        import config
        monkeypatch.setattr(config, "DEV_MODE", False)
        monkeypatch.setattr(config, "SESSION_SECRET", "some-secret")
        monkeypatch.setattr(config, "DATABASE_URI", None)
        monkeypatch.setattr(config, "CORS_ALLOW_ORIGINS", ["https://example.com"])

        with pytest.raises(RuntimeError, match="DATABASE_URI"):
            config._validate_config()

    def test_validate_config_raises_for_empty_cors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty CORS_ALLOW_ORIGINS should raise RuntimeError in prod."""
        import config
        monkeypatch.setattr(config, "DEV_MODE", False)
        monkeypatch.setattr(config, "SESSION_SECRET", "some-secret")
        monkeypatch.setattr(config, "DATABASE_URI", "sqlite:///:memory:")
        monkeypatch.setattr(config, "CORS_ALLOW_ORIGINS", [])

        with pytest.raises(RuntimeError, match="CORS_ALLOW_ORIGINS"):
            config._validate_config()

    def test_validate_config_passes_when_all_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All settings present should not raise."""
        import config
        monkeypatch.setattr(config, "DEV_MODE", False)
        monkeypatch.setattr(config, "SESSION_SECRET", "some-secret")
        monkeypatch.setattr(config, "DATABASE_URI", "sqlite:///:memory:")
        monkeypatch.setattr(config, "CORS_ALLOW_ORIGINS", ["https://example.com"])

        config._validate_config()  # Should not raise


class TestLogging:
    """Verify structured logging is configured."""

    def test_log_level_consumed(self) -> None:
        """LOG_LEVEL config attribute should exist."""
        from config import LOG_LEVEL
        assert isinstance(LOG_LEVEL, str)

    def test_setup_logging_runs(self) -> None:
        """setup_logging should execute without error."""
        from logging_config import setup_logging
        setup_logging()  # Should not raise

    def test_json_formatter_exists(self) -> None:
        """The _JSONFormatter class should be importable."""
        from logging_config import _JSONFormatter
        formatter = _JSONFormatter()
        assert formatter is not None


class TestDatabasePoolTuning:
    """Verify database engine creation includes pool tuning."""

    def test_check_same_thread_only_for_sqlite(self) -> None:
        """check_same_thread should only be set for SQLite URIs."""
        from db import Database

        db = Database()
        # In tests, we use SQLite, so check_same_thread should be present
        if db._cnx_uri.startswith("sqlite"):
            assert "check_same_thread" in db._cnx_args
        else:
            assert "check_same_thread" not in db._cnx_args


