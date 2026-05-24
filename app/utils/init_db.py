"""
Create all ORM tables on PostgreSQL (e.g. a fresh Neon database).

Run once after DATABASE_URL is set in .env:

    python -m app.utils.init_db

Reset database and seed only the system administrator:

    python -m app.utils.reset_db

Optional full demo seed (dev only):

    python -m app.utils.seed_data

Seed system admin only (without reset):

    python -m app.utils.seed_data --admin-only

Uses schema ``rental_mgr`` by default (see ``database_schema`` in config) so tables
do not collide with Neon Auth / other ``public.*`` objects.
"""
import logging
from pathlib import Path

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
    PaymentCheckout,
    Invoice,
    MaintenanceRequest,
    Notification,
    AuditLog,
    GovernmentInvitation,
    GovLoginSession,
    SavedUnit,
    MessageThread,
    ThreadParticipant,
    BlockchainWallet,
    BlockchainReceipt,
    EscrowHold,
)

logger = logging.getLogger(__name__)

# Bump when startup migration steps change; local stamp skips slow Neon round-trips on reload.
_STARTUP_STAMP_VERSION = "v12-enterprise-receipts"
_STARTUP_STAMP_FILE = Path(__file__).resolve().parent.parent.parent / ".startup_migrations.stamp"


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
        ("national_id_number", "VARCHAR(20) NULL", "VARCHAR(20) NULL", "VARCHAR(20) NULL"),
        ("gov_agency", "VARCHAR(24) NULL", "VARCHAR(24) NULL", "VARCHAR(24) NULL"),
        ("gov_work_id", "VARCHAR(64) NULL", "VARCHAR(64) NULL", "VARCHAR(64) NULL"),
        ("gov_security_pin_hash", "VARCHAR(255) NULL", "VARCHAR(255) NULL", "VARCHAR(255) NULL"),
        ("gov_2fa_enabled", "BOOLEAN NOT NULL DEFAULT false", "INTEGER NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT false"),
        ("gov_2fa_otp", "VARCHAR(10) NULL", "VARCHAR(10) NULL", "VARCHAR(10) NULL"),
        ("gov_2fa_otp_expiry", "TIMESTAMP WITHOUT TIME ZONE NULL", "DATETIME NULL", "TIMESTAMP NULL"),
        ("gov_onboarding_complete", "BOOLEAN NOT NULL DEFAULT false", "INTEGER NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT false"),
    ]
    for col_name, ddl_pg, ddl_sqlite, ddl_other in _user_column_ddls:
        add_column(col_name, ddl_pg, ddl_sqlite, ddl_other)

    try:
        with engine.begin() as conn:
            if is_pg:
                conn.execute(
                    text(
                        f"UPDATE {qual} SET gov_onboarding_complete = true "
                        "WHERE role::text LIKE 'gov_%' OR role::text = 'system_admin'"
                    )
                )
            elif is_sqlite:
                conn.execute(
                    text(
                        f"UPDATE {qual} SET gov_onboarding_complete = 1 "
                        "WHERE role LIKE 'gov_%' OR role = 'system_admin'"
                    )
                )
            else:
                conn.execute(
                    text(
                        f"UPDATE {qual} SET gov_onboarding_complete = 1 "
                        "WHERE role LIKE 'gov_%' OR role = 'system_admin'"
                    )
                )
        logger.info("Marked existing government users as onboarding-complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not backfill gov_onboarding_complete: %s", exc)


def ensure_tenants_column_migrations() -> None:
    """Add columns on ``tenants`` that older Neon/Alembic schemas lack."""
    from app.config import settings

    insp = inspect(engine)
    schema = postgres_table_schema if postgres_table_schema else None
    try:
        if not insp.has_table("tenants", schema=schema):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_tenants_column_migrations: could not inspect tenants: %s", exc)
        return

    try:
        col_names = {c["name"] for c in insp.get_columns("tenants", schema=schema)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_tenants_column_migrations: get_columns failed: %s", exc)
        return

    url = settings.database_url.lower()
    is_pg = "postgresql" in url
    is_sqlite = "sqlite" in url
    qual = f'"{schema}"."tenants"' if schema else "tenants"

    def add_column(name: str, ddl_pg: str, ddl_sqlite: str, ddl_other: str) -> None:
        nonlocal col_names
        if name in col_names:
            return
        ddl = ddl_pg if is_pg else (ddl_sqlite if is_sqlite else ddl_other)
        stmt = f"ALTER TABLE {qual} ADD COLUMN {name} {ddl}"
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            logger.info("Added missing column tenants.%s", name)
            col_names.add(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not add tenants.%s: %s", name, exc)

    _tenant_column_ddls = [
        ("user_id", "INTEGER NULL", "INTEGER NULL", "INTEGER NULL"),
    ]
    for col_name, ddl_pg, ddl_sqlite, ddl_other in _tenant_column_ddls:
        add_column(col_name, ddl_pg, ddl_sqlite, ddl_other)


def ensure_payments_column_migrations() -> None:
    """Add columns on ``payments`` that older schemas lack."""
    from app.config import settings

    insp = inspect(engine)
    schema = postgres_table_schema if postgres_table_schema else None
    try:
        if not insp.has_table("payments", schema=schema):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_payments_column_migrations: could not inspect payments: %s", exc)
        return

    try:
        col_names = {c["name"] for c in insp.get_columns("payments", schema=schema)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_payments_column_migrations: get_columns failed: %s", exc)
        return

    url = settings.database_url.lower()
    is_pg = "postgresql" in url
    is_sqlite = "sqlite" in url
    qual = f'"{schema}"."payments"' if schema else "payments"

    def add_column(name: str, ddl_pg: str, ddl_sqlite: str, ddl_other: str) -> None:
        nonlocal col_names
        if name in col_names:
            return
        ddl = ddl_pg if is_pg else (ddl_sqlite if is_sqlite else ddl_other)
        stmt = f"ALTER TABLE {qual} ADD COLUMN {name} {ddl}"
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            logger.info("Added missing column payments.%s", name)
            col_names.add(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not add payments.%s: %s", name, exc)

    _payment_column_ddls = [
        ("lease_id", "INTEGER NULL", "INTEGER NULL", "INTEGER NULL"),
        ("owner_id", "INTEGER NULL", "INTEGER NULL", "INTEGER NULL"),
        (
            "payment_type",
            "VARCHAR(20) NOT NULL DEFAULT 'rent'",
            "VARCHAR(20) NOT NULL DEFAULT 'rent'",
            "VARCHAR(20) NOT NULL DEFAULT 'rent'",
        ),
        ("reference", "VARCHAR(100) NULL", "VARCHAR(100) NULL", "VARCHAR(100) NULL"),
        ("updated_at", "TIMESTAMP WITHOUT TIME ZONE NULL", "DATETIME NULL", "TIMESTAMP NULL"),
    ]
    for col_name, ddl_pg, ddl_sqlite, ddl_other in _payment_column_ddls:
        add_column(col_name, ddl_pg, ddl_sqlite, ddl_other)

    if is_pg and "owner_id" in col_names:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"""
                        UPDATE {qual} p
                        SET owner_id = t.owner_id
                        FROM "{schema}"."tenants" t
                        WHERE p.tenant_id = t.id AND p.owner_id IS NULL
                        """
                        if schema
                        else """
                        UPDATE payments p
                        SET owner_id = t.owner_id
                        FROM tenants t
                        WHERE p.tenant_id = t.id AND p.owner_id IS NULL
                        """
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not backfill payments.owner_id: %s", exc)

    # Legacy columns from older payment schema — allow ORM inserts without them.
    if is_pg:
        for legacy_col in ("recorded_by", "receipt_number"):
            if legacy_col in col_names:
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                f"ALTER TABLE {qual} ALTER COLUMN {legacy_col} DROP NOT NULL"
                            )
                        )
                    logger.info("Relaxed NOT NULL on payments.%s", legacy_col)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not alter payments.%s: %s", legacy_col, exc)


def ensure_government_schema_migrations() -> None:
    """Government portal columns + PostgreSQL enum values for gov_* roles."""
    from app.config import settings

    insp = inspect(engine)
    schema = postgres_table_schema if postgres_table_schema else None
    url = settings.database_url.lower()
    is_pg = "postgresql" in url

    if is_pg:
        for val in ("system_admin", "gov_super", "gov_nira", "gov_kcca", "gov_ura"):
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{val}'"))
                logger.info("Ensured userrole enum value %s", val)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not add userrole.%s: %s", val, exc)
        try:
            qual = f'"{schema}"."users"' if schema else "users"
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"UPDATE {qual} SET role = 'system_admin' "
                        "WHERE role::text IN ('admin', 'gov_super')"
                    )
                )
            logger.info("Migrated legacy admin/gov_super users to system_admin")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not migrate admin users: %s", exc)
    else:
        try:
            qual = "users"
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"UPDATE {qual} SET role = 'system_admin' "
                        "WHERE role IN ('admin', 'gov_super')"
                    )
                )
            logger.info("Migrated legacy admin/gov_super users to system_admin")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not migrate admin users: %s", exc)

    try:
        if insp.has_table("users", schema=schema):
            col_names = {c["name"] for c in insp.get_columns("users", schema=schema)}
            qual = f'"{schema}"."users"' if schema else "users"
            if "national_id_number" not in col_names:
                ddl = "VARCHAR(20) NULL"
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {qual} ADD COLUMN national_id_number {ddl}"))
                logger.info("Added users.national_id_number")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_government_schema_migrations users: %s", exc)

    try:
        if insp.has_table("properties", schema=schema):
            col_names = {c["name"] for c in insp.get_columns("properties", schema=schema)}
            qual = f'"{schema}"."properties"' if schema else "properties"
            if "gov_verification_status" not in col_names:
                ddl = "VARCHAR(24) NOT NULL DEFAULT 'pending'"
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {qual} ADD COLUMN gov_verification_status {ddl}"))
                logger.info("Added properties.gov_verification_status")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_government_schema_migrations properties: %s", exc)


def ensure_government_invitation_tables() -> None:
    """Create invitation & session tables; extend users for gov onboarding."""
    from app.models.government_invitation import GovernmentInvitation
    from app.models.gov_login_session import GovLoginSession

    try:
        GovernmentInvitation.__table__.create(bind=engine, checkfirst=True)
        GovLoginSession.__table__.create(bind=engine, checkfirst=True)
        logger.info("Ensured government_invitations and gov_login_sessions tables")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_government_invitation_tables: %s", exc)


def ensure_payment_checkout_table() -> None:
    """Create ``payment_checkouts`` on existing DBs (create_all skips existing metadata)."""
    from app.models.payment_checkout import PaymentCheckout

    try:
        PaymentCheckout.__table__.create(bind=engine, checkfirst=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_payment_checkout_table: %s", exc)


def ensure_blockchain_tables() -> None:
    """Create blockchain_wallets, blockchain_receipts, escrow_holds."""
    for model in (BlockchainWallet, BlockchainReceipt, EscrowHold):
        try:
            model.__table__.create(bind=engine, checkfirst=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_blockchain_tables (%s): %s", model.__tablename__, exc)


def ensure_receipt_tables() -> None:
    from app.models.system_receipt import SystemReceipt

    try:
        SystemReceipt.__table__.create(bind=engine, checkfirst=True)
        logger.info("Ensured system_receipts table")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_receipt_tables: %s", exc)


def run_incremental_migrations() -> None:
    """ALTER existing DBs — safe to run repeatedly."""
    ensure_users_column_migrations()
    ensure_tenants_column_migrations()
    ensure_payments_column_migrations()
    ensure_payment_checkout_table()
    ensure_blockchain_tables()
    ensure_receipt_tables()
    ensure_government_schema_migrations()
    ensure_government_invitation_tables()


def run_startup_migrations() -> None:
    """
    Lightweight boot migrations for uvicorn (no full init_tables).
    Skipped when SKIP_STARTUP_MIGRATIONS=true or stamp file matches version.
    """
    from app.config import settings

    if settings.skip_startup_migrations:
        logger.info("Startup migrations skipped (SKIP_STARTUP_MIGRATIONS).")
        return

    try:
        if _STARTUP_STAMP_FILE.exists():
            if _STARTUP_STAMP_FILE.read_text(encoding="utf-8").strip() == _STARTUP_STAMP_VERSION:
                logger.info("Startup migrations skipped (stamp %s).", _STARTUP_STAMP_VERSION)
                return
    except OSError as exc:
        logger.warning("Could not read migration stamp: %s", exc)

    logger.info("Running startup migrations…")
    run_incremental_migrations()
    try:
        _STARTUP_STAMP_FILE.write_text(_STARTUP_STAMP_VERSION, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write migration stamp: %s", exc)
    logger.info("Startup migrations complete.")


def run_all_migrations() -> None:
    """Create tables and apply incremental column / government migrations."""
    init_tables()
    run_incremental_migrations()


def reset_database() -> None:
    """
    Drop all application tables (or the whole Postgres schema) and recreate empty tables.
    """
    from app.config import settings

    url = settings.database_url.lower()
    is_pg = "postgresql" in url

    print("Resetting database…")
    if is_pg and postgres_table_schema:
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {postgres_table_schema} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {postgres_table_schema}"))
        print(f"   Dropped and recreated schema: {postgres_table_schema}")
    else:
        Base.metadata.drop_all(bind=engine)
        print("   Dropped all tables in public (from app metadata).")
        if is_pg:
            with engine.begin() as conn:
                conn.execute(text("DROP SCHEMA IF EXISTS rental_mgr CASCADE"))
            print("   Removed legacy schema rental_mgr (if it existed).")

    print("Recreating tables and applying migrations…")
    run_all_migrations()
    print("Database reset complete.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("--reset", "reset"):
        reset_database()
    else:
        print("Creating tables and applying migrations…")
        run_all_migrations()
        print("Done.")
