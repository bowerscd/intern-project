"""OIDC discovery and client credential configuration."""

from typing import Any

from datetime import timedelta
from starlette.datastructures import URL

_FIFTEEN_MINUTES = timedelta(minutes=15)


class AuthConfig:
    """OIDC discovery configuration and client credential manager.

    Fetches and caches the provider's ``/.well-known/openid-configuration``
    document, refreshing it after a configurable interval.
    """

    def __init__(
        self,
        site_root: str,
        var_prefix: str,
        update_interval: timedelta = _FIFTEEN_MINUTES,
    ) -> None:
        """Initialise the configuration manager.

        Client credentials and redirect URI are read from environment
        variables prefixed with *var_prefix* (upper-cased).

        :param site_root: Base URL of the OIDC provider (e.g.
            ``"https://accounts.google.com"``).
        :param var_prefix: Prefix for environment variables providing
            ``CLIENT_ID``, ``CLIENT_SECRET``, and ``REDIRECT_URI``.
        :param update_interval: How long to cache the well-known
            configuration before re-fetching.
        """
        from os import environ
        from asyncio.locks import Lock

        var_prefix = var_prefix.upper()

        self.__config_lock = Lock()
        self.__config_url = f"{site_root}/.well-known/openid-configuration"
        self.__config: Any = None

        self.__update_interval = update_interval

        self.__next_update = 0.0

        self.__redirect_url: URL = URL(environ[f"{var_prefix}_REDIRECT_URI"])
        self.__client_secret: str = environ[f"{var_prefix}_CLIENT_SECRET"]
        self.__client_id: str = environ[f"{var_prefix}_CLIENT_ID"]

    async def config(self) -> Any:
        """Return the cached OIDC configuration, refreshing if stale.

        :returns: The provider's OpenID Connect configuration dict.
        :rtype: Any
        :raises Exception: If the well-known endpoint returns a non-200
            status.
        """
        from http import HTTPStatus
        from aiohttp import ClientSession, ClientTimeout
        from datetime import datetime, UTC

        async with self.__config_lock:
            if datetime.now(UTC).timestamp() < self.__next_update:
                return self.__config

            async with ClientSession(timeout=ClientTimeout(total=10)) as c:
                result = await c.get(self.__config_url)
                if result.status != HTTPStatus.OK:
                    raise Exception(f"wellknown config returned: {result.status}")

                self.__next_update = (
                    datetime.now(UTC) + self.__update_interval
                ).timestamp()
                self.__config = await result.json()

                return self.__config

    @property
    def secret(self) -> str:
        """Return the client secret.

        :returns: The OIDC client secret.
        :rtype: str
        """
        return self.__client_secret

    @property
    def client_id(self) -> str:
        """Return the client ID.

        :returns: The OIDC client identifier.
        :rtype: str
        """
        return self.__client_id

    @property
    def redirect_url(self) -> URL:
        """Return the configured redirect URL.

        :returns: The OIDC redirect URI.
        :rtype: URL
        """
        return self.__redirect_url
