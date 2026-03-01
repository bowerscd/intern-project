"""Alembic environment configuration — ties migrations to the app's models.

This module is executed by the Alembic CLI (or programmatic API) during
``upgrade``, ``downgrade``, ``revision --autogenerate``, etc.

It imports the application's :class:`~models.database.Model` metadata so
that ``--autogenerate`` can compare the ORM definitions against the
current database schema and emit the appropriate DDL.

The database URL is resolved at runtime in the following priority:

1. ``-x sqlalchemy.url=...`` CLI override
2. ``config.DATABASE_URI`` (reads ``settings.json`` → ``DATABASE_URI`` env var)
3. Alembic's ``sqlalchemy.url`` in ``alembic.ini`` (left blank by default)
"""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

# -- Import every model so metadata.tables is fully populated ---------------
# The models/__init__.py re-exports all ORM classes, which triggers their
# registration on Model.metadata.
import models  # noqa: F401
from models.database import Model
from models.internal import SqlValueEnum

target_metadata = Model.metadata


def _render_item(type_: str, obj: object, autogen_context: Any) -> str | bool:
    """Custom render hook so ``SqlValueEnum`` columns are emitted as ``sa.Integer()``.

    Without this, Alembic would emit ``models.internal.SqlValueEnum()`` in
    migration scripts, requiring the application code to be importable at
    migration time.

    :param type_: Alembic render type (``"type"``, ``"server_default"``, …).
    :param obj: The SQLAlchemy type or default being rendered.
    :param autogen_context: Alembic autogeneration context.
    :returns: A string representation, or ``False`` to fall through to
        the default renderer.
    """
    if type_ == "type" and isinstance(obj, SqlValueEnum):
        return "sa.Integer()"
    return False


def _compare_type(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Suppress false-positive type diffs for :class:`SqlValueEnum` columns.

    ``SqlValueEnum`` stores integer values and its ``impl`` is
    ``Integer``, so the on-disk column is ``INTEGER``.  Without this
    hook Alembic would report it as a type change every time.

    :returns: ``False`` to suppress the diff, or ``None`` to let
        Alembic's default comparison proceed.
    """
    from sqlalchemy import Integer

    if isinstance(metadata_type, SqlValueEnum) and isinstance(inspected_type, Integer):
        return False
    return None


# -- Alembic Config object (wraps alembic.ini) ------------------------------
config = context.config

# Resolve the database URL:
#   1. CLI override:  -x sqlalchemy.url=sqlite:///path.db
#   2. App config:    config.DATABASE_URI (settings.json / env var)
#   3. alembic.ini:   sqlalchemy.url key (blank by default)
_url = (
    config.get_section_option("alembic", "sqlalchemy.url")
    or config.cmd_opts  # type: ignore[union-attr]
    and getattr(config.cmd_opts, "x", None)
    and dict(arg.split("=", 1) for arg in config.cmd_opts.x).get("sqlalchemy.url")  # type: ignore[union-attr]
)
if not _url:
    try:
        from config import DATABASE_URI

        if DATABASE_URI:
            _url = DATABASE_URI
    except Exception:
        pass

if _url:
    config.set_main_option("sqlalchemy.url", _url)

# Set up Python logging from alembic.ini (preserve loggers created
# before Alembic runs — e.g. pytest's ``LogCaptureHandler``).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL without connecting.

    Calls ``context.configure`` with just a URL so Alembic can emit
    ``BEGIN``/``COMMIT`` and raw DDL to stdout (or a script file).
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE
        render_item=_render_item,
        compare_type=_compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects and applies DDL directly.

    Creates an :class:`~sqlalchemy.engine.Engine` from the resolved URL,
    binds a connection to the Alembic context, and runs the migration
    steps inside a transaction.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE
            render_item=_render_item,
            compare_type=_compare_type,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
