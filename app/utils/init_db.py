"""
Create all ORM tables on PostgreSQL (e.g. a fresh Neon database).

Run once after DATABASE_URL is set in .env:

    python -m app.utils.init_db

Optional: load sample rows for local development (not required for production):

    python -m app.utils.seed_data

Uses schema ``rental_mgr`` by default (see ``database_schema`` in config) so tables
do not collide with Neon Auth / other ``public.*`` objects.
"""
from sqlalchemy import text

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
)


def init_tables() -> None:
    if postgres_table_schema:
        with engine.begin() as conn:
            conn.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {postgres_table_schema}")
            )
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    print("Creating tables from SQLAlchemy metadata…")
    init_tables()
    print("Done.")
