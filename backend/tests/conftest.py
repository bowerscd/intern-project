"""Shared pytest fixtures — database, HTTP clients, SMTP, and auth helpers."""

from typing import Any, Tuple

import pytest
import pytest_asyncio
from pytest_localserver.smtp import Server as SMTPServer

from fastapi.testclient import TestClient

from app import app
from routes.shared import AUTH_SESSION_KEY

from db import Database
from db.functions import create_account

from models import AccountClaims, AccountStatus, ExternalAuthProvider

from . import ENV_VAR_OVERRIDES
from collections.abc import AsyncIterator
from collections.abc import Generator
from collections.abc import Iterator
from http.cookiejar import Cookie
from sqlalchemy.orm import Session


@pytest.fixture(scope="session", autouse=True)
def disable_csrf_globally() -> Generator[None, None, None]:
    """Override the CSRF validation dependency with a no-op for all tests.

    CSRF is validated at the integration level; unit/functional tests
    should not be blocked by it.
    """
    from csrf import validate_csrf_token

    async def _noop(request: Any = None) -> None:
        pass

    app.dependency_overrides[validate_csrf_token] = _noop
    yield
    app.dependency_overrides.pop(validate_csrf_token, None)


@pytest.fixture(scope="session", autouse=True)
def tests_setup_and_teardown() -> Generator[None, None, None]:
    """Apply test environment variable overrides for the entire session."""
    from os import environ

    old = environ.copy()
    environ.update(ENV_VAR_OVERRIDES)

    yield

    environ.clear()
    environ.update(old)


@pytest_asyncio.fixture(scope="function")
async def smtp(smtpserver: SMTPServer) -> SMTPServer:
    """Configure an in-process SMTP server and inject its URI into the env.

    :param smtpserver: pytest-localserver SMTP fixture.
    :type smtpserver: SMTPServer
    :returns: The running SMTP server instance.
    :rtype: SMTPServer
    """
    from os import environ

    old = environ.copy()

    assert isinstance(smtpserver.addr, tuple)
    smtp_addr: Tuple[str, int] = smtpserver.addr

    host = smtp_addr[0]
    if host == "::1":
        host = "localhost"

    environ["SMTP_URI"] = f"smtp://doesnotmatter:notapassword@{host}:{smtp_addr[1]}"
    environ["MAIL_SENDER"] = "pytest@localhost"

    # Reset cached mail config
    import mail

    mail.__smtp_host_url = None
    mail.__sender_email = None

    yield smtpserver

    environ.clear()
    environ.update(old)

    mail.__smtp_host_url = None
    mail.__sender_email = None


@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncIterator[TestClient]:
    """Yield an unauthenticated :class:`~fastapi.testclient.TestClient`."""
    from ratelimit import limiter

    limiter.reset()
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture(scope="function")
async def authenticated_client(database: Database) -> AsyncIterator[TestClient]:
    """
    Creates a test account with ALL claims, forges a signed session cookie,
    and returns a TestClient that is pre-authenticated.

    :param database: Started database instance.
    :type database: Database
    """
    from ratelimit import limiter

    limiter.reset()

    def mk_auth_cookie(value: Any) -> Cookie:
        """Build a signed session cookie for the test client.

        :param value: Session payload to serialize into the cookie.
        :type value: Any
        :returns: A configured :class:`~http.cookiejar.Cookie`.
        :rtype: Cookie
        """
        from json import dumps
        from base64 import b64encode
        from http.cookiejar import Cookie

        from itsdangerous import TimestampSigner
        from datetime import datetime, UTC, timedelta

        from routes import SESSION_COOKIE_NAME

        signer = TimestampSigner(secret_key=str(secret))

        _signed_value = signer.sign(b64encode(dumps(value).encode("utf-8"))).decode(
            "utf-8"
        )
        kwargs = {
            "version": 0,
            "name": SESSION_COOKIE_NAME,
            "value": _signed_value,
            "port": None,
            "port_specified": False,
            "domain": "",
            "domain_specified": False,
            "domain_initial_dot": False,
            "path": "/",
            "path_specified": True,
            "secure": False,
            "expires": (datetime.now(UTC) + timedelta(seconds=60 * 60)).timestamp(),
            "discard": True,
            "comment": None,
            "comment_url": None,
            "rest": {"HttpOnly": True, "SameSite": "lax"},
            "rfc2109": False,
        }

        return Cookie(**kwargs)  # type: ignore

    from app import secret

    claim: AccountClaims = AccountClaims.ANY

    with database.session() as s:
        act = create_account(
            "test",
            "test@test.com",
            ExternalAuthProvider.test,
            "1",
            None,
            claims=claim,
        )
        act.status = AccountStatus.ACTIVE
        s.add(act)
        s.commit()

        with TestClient(app) as c:
            c.cookies.jar.set_cookie(mk_auth_cookie({AUTH_SESSION_KEY: act.id}))
            yield c


@pytest.fixture(scope="function")
def database() -> Iterator[Database]:
    """Yield a started :class:`~db.Database` instance, stopped on teardown."""
    with Database() as db:
        yield db


def _mk_auth_cookie(secret: Any, account_id: int) -> Cookie:
    """Build a signed session cookie for the test client.

    :param secret: The signing secret.
    :param account_id: The account ID to embed in the session.
    :returns: A configured :class:`~http.cookiejar.Cookie`.
    :rtype: Cookie
    """
    from json import dumps
    from base64 import b64encode

    from itsdangerous import TimestampSigner
    from datetime import datetime, UTC, timedelta

    from routes import SESSION_COOKIE_NAME

    signer = TimestampSigner(secret_key=str(secret))

    _signed_value = signer.sign(
        b64encode(dumps({AUTH_SESSION_KEY: account_id}).encode("utf-8"))
    ).decode("utf-8")
    kwargs = {
        "version": 0,
        "name": SESSION_COOKIE_NAME,
        "value": _signed_value,
        "port": None,
        "port_specified": False,
        "domain": "",
        "domain_specified": False,
        "domain_initial_dot": False,
        "path": "/",
        "path_specified": True,
        "secure": False,
        "expires": (datetime.now(UTC) + timedelta(seconds=60 * 60)).timestamp(),
        "discard": True,
        "comment": None,
        "comment_url": None,
        "rest": {"HttpOnly": True, "SameSite": "lax"},
        "rfc2109": False,
    }
    return Cookie(**kwargs)  # type: ignore


def _authenticated_client_with_claims(
    database: Database, claims: AccountClaims, username: str = "test"
) -> Iterator[TestClient]:
    """Helper: create a test account with *claims* and return a pre-authenticated client.

    :param database: Started database instance.
    :param claims: The claim bitmask for the test account.
    :param username: Username for the account.
    """
    from ratelimit import limiter
    from app import secret

    limiter.reset()

    with database.session() as s:
        act = create_account(
            username,
            f"{username}@test.com",
            ExternalAuthProvider.test,
            "1",
            None,
            claims=claims,
        )
        act.status = AccountStatus.ACTIVE
        s.add(act)
        s.commit()

        with TestClient(app) as c:
            c.cookies.jar.set_cookie(_mk_auth_cookie(secret, act.id))
            yield c


@pytest_asyncio.fixture(scope="function")
async def mealbot_only_client(database: Database) -> AsyncIterator[TestClient]:
    """Authenticated client with only the MEALBOT claim.

    Use this fixture to verify that MEALBOT-only users cannot access
    HAPPY_HOUR endpoints and vice-versa.
    """
    for c in _authenticated_client_with_claims(
        database, AccountClaims.MEALBOT, "mealbot_user"
    ):
        yield c


@pytest_asyncio.fixture(scope="function")
async def happyhour_only_client(database: Database) -> AsyncIterator[TestClient]:
    """Authenticated client with only the HAPPY_HOUR claim.

    Use this fixture to verify that HAPPY_HOUR-only users cannot access
    MEALBOT endpoints.
    """
    for c in _authenticated_client_with_claims(
        database, AccountClaims.HAPPY_HOUR, "hh_user"
    ):
        yield c


@pytest.fixture(scope="function")
def db_session(database: Database) -> Iterator[Session]:
    """Yield a SQLAlchemy session scoped to a single test function.

    :param database: The database fixture.
    :type database: Database
    """
    with database.session() as s:
        yield s
