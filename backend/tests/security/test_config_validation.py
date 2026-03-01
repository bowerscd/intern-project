"""Config validation tests.

Validates that the config module handles various input scenarios correctly:
- Missing settings file
- Missing environment variables
- Default values
- Type coercion
"""

import pytest
import json
from pathlib import Path


class TestConfigGet:
    """Test the _get() configuration resolution function."""

    def test_env_var_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Environment variables should be used when settings.json key is missing."""
        import config

        # Write an empty settings file
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        monkeypatch.setattr(config, "_SETTINGS_PATH", settings_file)
        monkeypatch.setattr(config, "_settings", {})

        monkeypatch.setenv("TEST_CONFIG_VAR", "from_env")
        result = config._get("nonexistent_key", "TEST_CONFIG_VAR", "default")
        assert result == "from_env"

    def test_default_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Default value should be returned when neither source provides a value."""
        import config

        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")
        monkeypatch.setattr(config, "_SETTINGS_PATH", settings_file)
        monkeypatch.setattr(config, "_settings", {})

        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        result = config._get("nonexistent_key", "NONEXISTENT_VAR", "my_default")
        assert result == "my_default"

    def test_settings_json_takes_priority(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """settings.json values take priority over environment variables."""
        import config

        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"my_key": "from_file"}))
        monkeypatch.setattr(config, "_SETTINGS_PATH", settings_file)
        monkeypatch.setattr(config, "_settings", {})

        monkeypatch.setenv("MY_KEY_ENV", "from_env")
        result = config._get("my_key", "MY_KEY_ENV", "default")
        assert result == "from_file"

    def test_missing_settings_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing settings.json should fall through to env vars."""
        import config

        nonexistent = tmp_path / "does_not_exist.json"
        monkeypatch.setattr(config, "_SETTINGS_PATH", nonexistent)
        monkeypatch.setattr(config, "_settings", {})

        monkeypatch.setenv("FALLBACK_VAR", "fallback_value")
        result = config._get("any_key", "FALLBACK_VAR", "default")
        assert result == "fallback_value"


class TestDevModeConfig:
    """DEV_MODE should be correctly parsed."""

    def test_dev_mode_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEV=1 should result in DEV_MODE=True."""
        # The DEV env var is already set to "1" by test fixtures
        import config

        assert config.DEV_MODE is True

    def test_session_secret_required_in_prod(self) -> None:
        """SESSION_SECRET should be set (at least in tests/dev)."""
        import config

        assert config.SESSION_SECRET is not None


class TestCORSConfig:
    """CORS configuration validation."""

    def test_cors_list_type(self) -> None:
        """CORS_ALLOW_ORIGINS should be a list."""
        import config

        assert isinstance(config.CORS_ALLOW_ORIGINS, list)

    def test_auth_redirect_origins_list(self) -> None:
        """AUTH_REDIRECT_ORIGINS should be a list."""
        import config

        assert isinstance(config.AUTH_REDIRECT_ORIGINS, list)
