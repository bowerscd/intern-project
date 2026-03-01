"""Tests for all Flask page routes — status codes, template rendering, and
context variables injected into templates."""

import pytest


# Every page route and its expected title substring.
PUBLIC_ROUTES = [
    ("/login", "Login"),
    ("/auth/callback", "Auth Callback"),
    ("/auth/complete-registration", "Complete Registration"),
    ("/auth/claim-account", "Claim Account"),
    ("/happyhour", "Happy Hour"),
]

PROTECTED_ROUTES = [
    ("/", "Welcome"),
    ("/account", "Account"),
    ("/mealbot", "Mealbot"),
    ("/mealbot/individualized", "My Mealbot Summary"),
    ("/happyhour/manage", "Happy Hour Management"),
]


class TestPublicRoutes:
    """Routes in PUBLIC_PATHS should always return 200 regardless of auth."""

    @pytest.mark.parametrize("path, title", PUBLIC_ROUTES)
    def test_returns_200(self, client, path, title):
        resp = client.get(path)
        assert resp.status_code == 200

    @pytest.mark.parametrize("path, title", PUBLIC_ROUTES)
    def test_renders_html(self, client, path, title):
        resp = client.get(path)
        assert b"<!doctype html>" in resp.data.lower() or b"<html" in resp.data.lower()


class TestProtectedRoutesInMockMode:
    """In mock mode, all routes return 200 even without auth."""

    @pytest.mark.parametrize("path, title", PROTECTED_ROUTES)
    def test_returns_200_mock_mode(self, mock_client, path, title):
        resp = mock_client.get(path)
        assert resp.status_code == 200


class TestProtectedRoutesWithAuth:
    """Routes behind the auth gate return 200 when the session cookie is present."""

    @pytest.mark.parametrize("path, title", PROTECTED_ROUTES)
    def test_returns_200_with_session(self, authed_client, path, title):
        resp = authed_client.get(path)
        assert resp.status_code == 200


class TestContextVariables:
    """Template context variables are injected as data attributes on <body>."""

    def test_api_base_injected(self, mock_client):
        resp = mock_client.get("/login")
        assert b"data-api-base=" in resp.data

    def test_use_mock_injected(self, mock_client):
        resp = mock_client.get("/login")
        assert b"data-use-mock=" in resp.data

    def test_dev_mode_injected(self, mock_client):
        resp = mock_client.get("/login")
        assert b"data-dev-mode=" in resp.data


class TestStaticAssets:
    """Static file serving works."""

    def test_css_served(self, client):
        resp = client.get("/static/css/main.css")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/css")


class TestNotFound:
    """Unknown paths return 404."""

    def test_unknown_route(self, mock_client):
        resp = mock_client.get("/nonexistent-page")
        assert resp.status_code == 404
