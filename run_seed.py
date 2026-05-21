#!/usr/bin/env python3
"""
Script to run database seeding.

Usage:
  python run_seed.py              # full demo data (dev only)
  python run_seed.py --admin-only # system administrator only
"""
import sys

sys.path.insert(0, ".")

from app.utils.seed_data import seed_database, seed_system_admin_only

if __name__ == "__main__":
    admin_only = len(sys.argv) > 1 and sys.argv[1] in ("--admin-only", "admin")
    print("Running Rental Manager Database Seeder…")
    print("=" * 50)

    try:
        if admin_only:
            seed_system_admin_only()
        else:
            seed_database()
        print("=" * 50)
        print("Seeding completed successfully.")
    except Exception as e:
        print("=" * 50)
        print(f"Error: {e}")
        sys.exit(1)
