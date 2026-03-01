"""Shared pytest fixtures for the Flask frontend test suite."""

import pytest
from app import app as flask_app


@pytest.fixture()
def app():
    """Yield the Flask application configured for testing."""
    flask_app.config.update({"TESTING": True})
    yield flask_app


@pytest.fixture()
def client(app):
    """Yield a Flask test client."""
    return app.test_client()


@pytest.fixture()
def mock_client(app, monkeypatch):
    """Yield a test client with USE_MOCK=True (auth gate disabled)."""
    import app as app_module

    monkeypatch.setattr(app_module, "USE_MOCK", True)
    return app.test_client()


@pytest.fixture()
def authed_client(app, monkeypatch):
    """Yield a test client with a fake session cookie set.

    Sets USE_MOCK=False and USE_PROXY=True so the auth gate is active,
    then injects the expected session cookie.
    """
    import app as app_module

    monkeypatch.setattr(app_module, "USE_MOCK", False)
    monkeypatch.setattr(app_module, "USE_PROXY", True)
    monkeypatch.setattr(app_module, "SESSION_COOKIE_NAME", "test.session")
    c = app.test_client()
    c.set_cookie("test.session", "fake-signed-value", domain="localhost")
    return c


@pytest.fixture()
def unauthed_client(app, monkeypatch):
    """Yield a test client with no session cookie (auth gate active)."""
    import app as app_module

    monkeypatch.setattr(app_module, "USE_MOCK", False)
    monkeypatch.setattr(app_module, "USE_PROXY", True)
    monkeypatch.setattr(app_module, "SESSION_COOKIE_NAME", "test.session")
    return app.test_client()
