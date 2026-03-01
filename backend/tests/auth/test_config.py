"""Tests for AuthConfig."""

import pytest

from auth.config import AuthConfig
from tests import TEST_REDIRECT, TEST_CLIENT_ID, TEST_CLIENT_SECRET, TEST_ENV_VAR_PREFIX


class TestAuthConfig:
    """Verify :class:`~auth.config.AuthConfig` loads credentials from the environment."""

    def test_init_loads_env_vars(self) -> None:
        """Verify client ID, secret, and redirect URL are read from env vars."""
        cfg = AuthConfig(
            site_root="https://example.com",
            var_prefix=TEST_ENV_VAR_PREFIX,
        )
        assert cfg.client_id == TEST_CLIENT_ID
        assert cfg.secret == TEST_CLIENT_SECRET
        assert str(cfg.redirect_url) == TEST_REDIRECT

    def test_init_missing_env_raises(self) -> None:
        """Verify a :class:`KeyError` is raised when env vars are absent."""
        with pytest.raises(KeyError):
            AuthConfig(
                site_root="https://example.com",
                var_prefix="NONEXISTENT_PREFIX",
            )
