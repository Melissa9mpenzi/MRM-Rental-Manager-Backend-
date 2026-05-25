"""Map SQLAlchemy failures to actionable API messages (Neon / Vercel)."""
from __future__ import annotations

from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError


def database_error_response(exc: SQLAlchemyError) -> tuple[str, int]:
    """
    Return (message, http_status) for auth and other DB-dependent routes.
    """
    detail = str(getattr(exc, "orig", exc) or exc).lower()

    if isinstance(exc, OperationalError):
        if "channel_binding" in detail:
            return (
                "Database SSL connection failed. On Vercel, set DATABASE_URL with "
                "?sslmode=require only (remove channel_binding=require). Use the Neon pooler host.",
                503,
            )
        if "password authentication failed" in detail or "authentication failed" in detail:
            return (
                "Database credentials rejected. Copy a fresh connection string from Neon "
                "(Dashboard → Connection details → pooled URI) into Vercel DATABASE_URL.",
                503,
            )
        if "timeout" in detail or "timed out" in detail:
            return (
                "Database connection timed out. Use Neon’s pooled endpoint (-pooler in the host) "
                "and confirm the project is not suspended.",
                503,
            )
        return (
            "Could not reach the database. Check DATABASE_URL on Vercel and that Neon allows connections.",
            503,
        )

    if isinstance(exc, ProgrammingError):
        if "does not exist" in detail:
            return (
                "Database tables are missing. From your machine, with the same Neon URL in .env, run: "
                "python -m app.utils.init_db — then try login again.",
                503,
            )
        return (
            "Database schema is out of date. Run python -m app.utils.init_db against Neon, then redeploy the API.",
            503,
        )

    return (
        "Database error. Verify DATABASE_URL on Vercel matches your Neon project (pooler + sslmode=require).",
        503,
    )
