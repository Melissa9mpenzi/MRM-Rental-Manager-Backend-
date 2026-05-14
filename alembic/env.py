from logging.config import fileConfig
import os
import re
import sys

from alembic import context
from sqlalchemy import engine_from_config, event, pool

# ── Make sure app/ is importable from alembic/ ───────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings
from app.database import Base

# Import ALL models so Alembic can see them for autogenerate
from app.models import *  # noqa: F401, F403

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _postgres_schema() -> str | None:
    if "postgresql" not in settings.database_url.lower():
        return None
    s = (settings.database_schema or "").strip()
    if not s or s.lower() == "public":
        return None
    if not _IDENTIFIER.fullmatch(s):
        raise ValueError(
            f"Invalid database_schema {s!r}: use letters, digits, underscore only."
        )
    return s


PG_SCHEMA = _postgres_schema()

# Alembic Config object
config = context.config

# Override sqlalchemy.url from our settings (reads .env automatically)
config.set_main_option("sqlalchemy.url", settings.database_url)

# Logging setup
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MetaData for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    cfg_kw = dict(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    if PG_SCHEMA:
        cfg_kw["version_table_schema"] = PG_SCHEMA
    context.configure(**cfg_kw)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if PG_SCHEMA and "postgresql" in settings.database_url.lower():
        sch = PG_SCHEMA

        @event.listens_for(connectable, "connect")
        def _alembic_set_search_path(dbapi_connection, _connection_record):
            cur = dbapi_connection.cursor()
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {sch}")
            cur.execute(f"SET search_path TO {sch}, public")
            cur.close()

    with connectable.connect() as connection:
        cfg_kw = dict(connection=connection, target_metadata=target_metadata)
        if PG_SCHEMA:
            cfg_kw["version_table_schema"] = PG_SCHEMA
        context.configure(**cfg_kw)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()