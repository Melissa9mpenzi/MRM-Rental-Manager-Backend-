"""
Reset database, run migrations, and seed only the system administrator.

Usage (from backend root, with venv active and DATABASE_URL in .env):

    python -m app.utils.reset_db

Optional: skip seed after reset:

    python -m app.utils.reset_db --no-seed
"""
import sys

from sqlalchemy import text

from app.database import engine
from app.utils.init_db import reset_database
from app.utils.seed_data import seed_system_admin_only


def _test_connection() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Database connection OK.")


def main() -> None:
    seed = "--no-seed" not in sys.argv
    print("=" * 50)
    print("RentDirect — database reset")
    print("=" * 50)
    _test_connection()
    reset_database()
    if seed:
        seed_system_admin_only()
        print()
        print("System admin login:")
        print("  Email:    nakunguesther044@gmail.com")
        print("  Password: admin12")
    else:
        print("Skipped seed (--no-seed).")
    print("=" * 50)
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Failed: {exc}")
        sys.exit(1)
