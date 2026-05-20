from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.config import settings
from app.routers import auth, properties, dashboard, tenants, payments, notifications, maintenance, users, tenant_portal, leases, invoices, workspace, marketplace, saved_units, messages

# Ensure upload subdirectories exist
for sub in ["properties", "tenants", "receipts", "receipts/proofs", "maintenance", "kyc"]:
    os.makedirs(os.path.join(settings.upload_dir, sub), exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import logging

    from app.config import settings
    from app.services.gateway.config import gateway_public_status, is_gateway_configured
    from app.utils.init_db import ensure_users_column_migrations, ensure_payment_checkout_table

    ensure_users_column_migrations()
    ensure_payment_checkout_table()

    gw = gateway_public_status()
    log = logging.getLogger("uvicorn.error")
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

    yield


app = FastAPI(
    title="RentalMGR API",
    version="1.0.0",
    description="MRM Rental Manager — Property, Tenant & Payment Management API",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

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

app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

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


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": "1.0.0"}