"""List schemas and tables for the configured DATABASE_URL."""
import re

from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine, postgres_table_schema

safe = re.sub(r":([^:@/]+)@", ":****@", settings.database_url)
print("Connection:", safe.split("@")[-1] if "@" in safe else safe)
print("DATABASE_SCHEMA setting:", postgres_table_schema or "(default public)")
print()

with engine.connect() as conn:
    rows = conn.execute(
        text(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
            """
        )
    ).fetchall()

print(f"Total tables: {len(rows)}")
current = None
for schema, name in rows:
    if schema != current:
        current = schema
        print(f"\n[{schema}]")
    print(f"  - {name}")
