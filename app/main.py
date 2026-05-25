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

    migration_task = None
    if not is_serverless() and not settings.skip_startup_migrations:
        async def _background_migrations() -> None:
            try:
                await asyncio.to_thread(run_startup_migrations)
            except Exception as exc:  # noqa: BLE001
                log.warning("Background startup migrations failed: %s", exc)

        migration_task = asyncio.create_task(_background_migrations())

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

    # Accept HTTP immediately; migrations run in background (avoids reload timeouts).
    yield

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
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except SQLAlchemyError as exc:
        return {
            "status": "error",
            "database": "connection_failed",
            "detail": str(exc)[:240],
        }
