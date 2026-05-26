"""Lightweight column introspection for older Neon / SQLite schemas."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import inspect as sa_inspect

from app.database import engine, postgres_table_schema


@lru_cache(maxsize=16)
def table_columns(table: str) -> frozenset[str]:
    insp = sa_inspect(engine)
    schema = postgres_table_schema
    try:
        if not insp.has_table(table, schema=schema):
            return frozenset()
        return frozenset(c["name"] for c in insp.get_columns(table, schema=schema))
    except Exception:  # noqa: BLE001
        return frozenset()
