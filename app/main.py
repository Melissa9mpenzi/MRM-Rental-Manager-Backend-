from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.config import settings
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
)

# Writable upload root (Vercel/Lambda only allow /tmp; project dir is read-only).
UPLOAD_ROOT = upload_root()
for sub in ["properties", "tenants", "receipts", "receipts/proofs", "maintenance", "kyc"]:
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
_cors_origins = list(dict.fromkeys(_local_vite + list(settings.allowed_origins)))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": "1.0.0"}
