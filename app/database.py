import re
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.runtime import is_serverless

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _postgres_schema() -> str | None:
    if "postgresql" not in settings.database_url.lower():
        return None
    s = (settings.database_schema or "").strip()
    if not s or s.lower() == "public":
        return None
    if not _IDENTIFIER.fullmatch(s):
        raise ValueError(
            f"Invalid database_schema {s!r}: use letters, digits, underscore only "
            "(e.g. rental_mgr)."
        )
    return s


postgres_table_schema: str | None = _postgres_schema()

_metadata = MetaData(schema=postgres_table_schema) if postgres_table_schema else MetaData()


class Base(DeclarativeBase):
    metadata = _metadata


_connect_args: dict = {}
if "postgresql" in settings.database_url.lower():
    # Neon / remote Postgres: slow or flaky networks need more than the default timeout.
    _connect_args["connect_timeout"] = 60

_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "echo": settings.environment == "development",
    "connect_args": _connect_args,
}
# Serverless: one connection per invocation — avoid pooled connections across frozen containers.
if is_serverless():
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(settings.database_url, **_engine_kwargs)

if postgres_table_schema:

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record):
        cur = dbapi_connection.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {postgres_table_schema}")
        cur.execute(f"SET search_path TO {postgres_table_schema}, public")
        cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
