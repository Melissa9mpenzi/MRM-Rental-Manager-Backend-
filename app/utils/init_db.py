"""
Create all ORM tables on PostgreSQL (e.g. a fresh Neon database).

Run once after DATABASE_URL is set in .env:

    python -m app.utils.init_db

Optional: load sample rows for local development (not required for production):

    python -m app.utils.seed_data

Uses schema ``rental_mgr`` by default (see ``database_schema`` in config) so tables
do not collide with Neon Auth / other ``public.*`` objects.
"""
import logging

from sqlalchemy import inspect, text

from app.database import Base, engine, postgres_table_schema

# Import models so they register on Base.metadata
from app.models import (  # noqa: F401
    User,
    Property,
    Unit,
    Tenant,
    Lease,
    Payment,
    Invoice,
    MaintenanceRequest,
    Notification,
    AuditLog,
    SavedUnit,
    MessageThread,
    ThreadParticipant,
    Message,
)

logger = logging.getLogger(__name__)


def init_tables() -> None:
    if postgres_table_schema:
        with engine.begin() as conn:
            conn.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {postgres_table_schema}")
            )
    Base.metadata.create_all(bind=engine)


def ensure_users_column_migrations() -> None:
    """
    Add columns introduced after the DB was first created.
    Base.metadata.create_all() does not ALTER existing tables.
    """
    from app.config import settings

    insp = inspect(engine)
    schema = postgres_table_schema if postgres_table_schema else None
    try:
        if not insp.has_table("users", schema=schema):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_users_column_migrations: could not inspect users: %s", exc)
        return

    try:
        col_names = {c["name"] for c in insp.get_columns("users", schema=schema)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_users_column_migrations: get_columns failed: %s", exc)
        return

    url = settings.database_url.lower()
    is_pg = "postgresql" in url
    is_sqlite = "sqlite" in url
    qual = f'"{schema}"."users"' if schema else "users"

    def add_column(name: str, ddl_pg: str, ddl_sqlite: str, ddl_other: str) -> None:
        nonlocal col_names
        if name in col_names:
            return
        ddl = ddl_pg if is_pg else (ddl_sqlite if is_sqlite else ddl_other)
        stmt = f"ALTER TABLE {qual} ADD COLUMN {name} {ddl}"
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            logger.info("Added missing column users.%s", name)
            col_names.add(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not add users.%s: %s", name, exc)

    # Keep in sync with app.models.user.User — older Alembic/Neon tables often lack these.
    _user_column_ddls = [
        ("reset_otp", "VARCHAR(10) NULL", "VARCHAR(10) NULL", "VARCHAR(10) NULL"),
        ("reset_otp_expiry", "TIMESTAMP WITHOUT TIME ZONE NULL", "DATETIME NULL", "TIMESTAMP NULL"),
        ("verification_token", "VARCHAR(100) NULL", "VARCHAR(100) NULL", "VARCHAR(100) NULL"),
        ("verification_token_expiry", "TIMESTAMP WITHOUT TIME ZONE NULL", "DATETIME NULL", "TIMESTAMP NULL"),
        ("verification_otp", "VARCHAR(10) NULL", "VARCHAR(10) NULL", "VARCHAR(10) NULL"),
        ("verification_otp_expiry", "TIMESTAMP WITHOUT TIME ZONE NULL", "DATETIME NULL", "TIMESTAMP NULL"),
        ("refresh_token", "VARCHAR(500) NULL", "VARCHAR(500) NULL", "VARCHAR(500) NULL"),
        ("kyc_submitted_at", "TIMESTAMP WITHOUT TIME ZONE NULL", "DATETIME NULL", "TIMESTAMP NULL"),
        (
            "kyc_review_status",
            "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "VARCHAR(20) NOT NULL DEFAULT 'none'",
        ),
        (
            "trusted_for_commerce",
            "BOOLEAN NOT NULL DEFAULT false",
            "INTEGER NOT NULL DEFAULT 0",
            "BOOLEAN NOT NULL DEFAULT false",
        ),
        ("firebase_uid", "VARCHAR(128) NULL", "VARCHAR(128) NULL", "VARCHAR(128) NULL"),
    ]
    for col_name, ddl_pg, ddl_sqlite, ddl_other in _user_column_ddls:
        add_column(col_name, ddl_pg, ddl_sqlite, ddl_other)


if __name__ == "__main__":
    print("Creating tables from SQLAlchemy metadata…")
    init_tables()
    print("Applying users column migrations…")
    ensure_users_column_migrations()
    print("Done.")
