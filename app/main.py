from contextlib import asynccontextmanager
import asyncio
import logging
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
import os

from app.config import database_url_looks_configured, settings
from app.runtime import is_serverless, upload_root
from app.routers import (
    auth,
    properties,
    dashboard,
    reports,
    tenants,
    payments,
    notifications,
    maintenance,
    users,
    tenant_portal,
    leases,
    invoices,
    workspace,
    marketplace,
    saved_units,
    messages,
    government,
    government_auth,
    blockchain,
    receipts,
    platform,
)

# Writable upload root (Vercel/Lambda only allow /tmp; project dir is read-only).
UPLOAD_ROOT = upload_root()
for sub in ["properties", "tenants", "receipts", "receipts/proofs", "receipts/enterprise", "maintenance", "kyc", "messages"]:
    os.makedirs(os.path.join(UPLOAD_ROOT, sub), exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.gateway.config import gateway_public_status, is_gateway_configured
    from app.utils.init_db import run_startup_migrations

    log = logging.getLogger("uvicorn.error")

    if "postgresql" in settings.database_url.lower():
        try:
            from sqlalchemy import inspect

            from app.database import engine, postgres_table_schema

            insp = inspect(engine)
            schema = postgres_table_schema
            if not insp.has_table("users", schema=schema):
                log.error(
                    "DATABASE_SCHEMA misconfigured: no users table in schema %r. "
                    "Set DATABASE_SCHEMA=public on Vercel if your Neon data is in public.*",
                    schema or "public",
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Schema health check skipped: %s", exc)

    migration_task = None
    if not settings.skip_startup_migrations:
        async def _run_migrations() -> None:
            try:
                await asyncio.to_thread(run_startup_migrations)
            except Exception as exc:  # noqa: BLE001
                log.warning("Startup migrations failed: %s", exc)

        # Serverless: schema must exist before first API request (gov overview, URA, fraud).
        if is_serverless():
            await _run_migrations()
        else:
            migration_task = asyncio.create_task(_run_migrations())

    gw = gateway_public_status()
    if settings.environment == "production" and not is_gateway_configured():
        log.error(
            "PAYMENTS: gateway not configured — set MTN MoMo or Pesapal keys (see docs/PAYMENT_GATEWAY.md)."
        )
    elif gw.get("mock_enabled"):
        log.warning("PAYMENTS: mock mode enabled (PAYMENT_ALLOW_MOCK) — not for real rent collection.")
    elif gw.get("configured"):
        log.info(
            "PAYMENTS: %s (%s) — Uganda collections enabled.",
            gw.get("provider"),
            gw.get("mode"),
        )

    reminder_task = None

    async def _rent_reminder_loop() -> None:
        await asyncio.sleep(45)
        while True:
            try:
                from app.services.rent_reminder_service import run_rent_reminder_job

                stats = await asyncio.to_thread(run_rent_reminder_job)
                if stats.get("tenant_notified") or stats.get("landlord_notified"):
                    log.info("Rent reminder job: %s", stats)
            except Exception as exc:  # noqa: BLE001
                log.warning("Rent reminder job failed: %s", exc)
            await asyncio.sleep(86400)

    reminder_task = asyncio.create_task(_rent_reminder_loop())

    # Accept HTTP immediately; migrations run in background (avoids reload timeouts).
    yield

    if reminder_task is not None:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass

    if migration_task is not None:
        migration_task.cancel()
        try:
            await migration_task
        except asyncio.CancelledError:
            pass


_app_kwargs: dict = {
    "title": "RentalMGR API",
    "version": "1.0.0",
    "description": "MRM Rental Manager — Property, Tenant & Payment Management API",
    "docs_url": "/docs",
    "redoc_url": "/redoc",
}
if not is_serverless():
    _app_kwargs["lifespan"] = lifespan

app = FastAPI(**_app_kwargs)

# CORS — explicit origins (merge so a narrow .env ALLOWED_ORIGINS never drops common Vite ports)
_local_vite = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]
_production_spa_origins = [
    "https://mrm-rental-manager-frontend-pink.vercel.app",
    "https://mrm-rental-manager-mobile.vercel.app",
]
_cors_origins = list(
    dict.fromkeys(_local_vite + _production_spa_origins + list(settings.allowed_origins))
)
# Any Vite port on localhost + all *.vercel.app preview/production frontends
_CORS_ORIGIN_RE = re.compile(
    r"^https://[\w.-]+\.vercel\.app$|^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    re.IGNORECASE,
)


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    if origin in _cors_origins:
        return True
    return bool(_CORS_ORIGIN_RE.match(origin))


class CorsFallbackMiddleware(BaseHTTPMiddleware):
    """Ensure CORS headers on errors/timeouts where default middleware may not run."""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")

        if request.method == "OPTIONS" and _origin_allowed(origin):
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": request.headers.get(
                        "access-control-request-headers", "*"
                    ),
                    "Access-Control-Max-Age": "86400",
                    "Vary": "Origin",
                },
            )

        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            logging.getLogger("uvicorn.error").exception("Unhandled error")
            response = JSONResponse(
                status_code=500,
                content={"success": False, "detail": "Internal server error"},
            )

        if _origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.setdefault("Vary", "Origin")
        return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"^https://[\w.-]+\.vercel\.app$|^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
# Outermost — runs first on request
app.add_middleware(CorsFallbackMiddleware)

app.mount("/uploads", StaticFiles(directory=UPLOAD_ROOT), name="uploads")

API = "/api/v1"
app.include_router(auth.router,         prefix=API)
app.include_router(users.router,        prefix=API)
app.include_router(properties.router,   prefix=API)
app.include_router(dashboard.router,    prefix=API)
app.include_router(reports.router,      prefix=API)
app.include_router(tenants.router,      prefix=API)
app.include_router(payments.router,     prefix=API)
app.include_router(maintenance.router,  prefix=API)
app.include_router(notifications.router, prefix=API)
app.include_router(tenant_portal.router,  prefix=API)
app.include_router(leases.router,       prefix=API)
app.include_router(invoices.router,     prefix=API)
app.include_router(workspace.router,   prefix=API)
app.include_router(marketplace.router, prefix=API)
app.include_router(saved_units.router, prefix=API)
app.include_router(messages.router,    prefix=API)
app.include_router(government.router,  prefix=API)
app.include_router(government_auth.router, prefix=API)
app.include_router(blockchain.router,     prefix=API)
app.include_router(receipts.router,         prefix=API)
app.include_router(platform.router,       prefix=API)


@app.get("/", tags=["Health"])
def root():
    """Landing for deploy previews and uptime checks (Vercel opens `/` by default)."""
    return {
        "service": "RentalMGR API",
        "status": "ok",
        "version": "1.0.0",
        "health": "/health",
        "docs": "/docs",
        "api": API,
        "frontend": "https://mrm-rental-manager-frontend-pink.vercel.app",
        "mobile_web": "https://mrm-rental-manager-mobile.vercel.app",
    }


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "database_configured": database_url_looks_configured(),
    }


@app.get("/health/db", tags=["Health"])
def health_db():
    """Verify Postgres/Neon connectivity (use after setting DATABASE_URL on Vercel)."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.config import database_url_looks_configured
    from app.database import engine

    if not database_url_looks_configured():
        return {
            "status": "error",
            "database": "not_configured",
            "hint": "Set DATABASE_URL on Vercel (postgresql+psycopg2://...neon.tech/...?sslmode=require)",
        }
    schema = (settings.database_schema or "public").strip()
    table_schema = schema if schema and schema.lower() != "public" else "public"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = 'users' LIMIT 1"
                ),
                {"s": table_schema},
            ).first()
            if not row:
                return {
                    "status": "error",
                    "database": "connected",
                    "schema": table_schema,
                    "app_tables": "missing_run_init_db",
                    "hint": (
                        "Neon is reachable but app tables are missing. Run "
                        "python -m app.utils.init_db with the same DATABASE_URL, then retry login."
                    ),
                }
        return {
            "status": "ok",
            "database": "connected",
            "schema": table_schema,
            "app_tables": "ready",
        }
    except SQLAlchemyError as exc:
        from app.db_errors import database_error_response

        msg, _ = database_error_response(exc)
        detail = str(getattr(exc, "orig", exc) or exc)[:240]
        app_tables = "unknown"
        if "does not exist" in detail.lower() or "undefinedtable" in detail.lower():
            app_tables = "missing_run_init_db"
        return {
            "status": "error",
            "database": "connection_failed" if "does not exist" not in detail.lower() else "schema_missing",
            "schema": schema,
            "app_tables": app_tables,
            "detail": detail,
            "hint": msg,
        }
