"""Production readiness checks — no mock data, real gateways and chain config."""
from __future__ import annotations

from typing import Any

from app.config import settings, database_url_looks_configured
from app.services.blockchain import blockchain_service, walrus_service
from app.services.gateway.config import gateway_public_status, is_gateway_configured, is_mock_allowed
from app.services import cloudinary_storage_service, privy_token_service
from app.services.public_url_service import api_public_base_url, frontend_base_url


def production_readiness() -> dict[str, Any]:
    """Checklist for global presentation — all items should be green on Vercel."""
    gw = gateway_public_status()
    chain = blockchain_service.blockchain_public_status()
    issues: list[str] = []
    warnings: list[str] = []

    if not database_url_looks_configured():
        issues.append("DATABASE_URL is not configured.")
    if settings.is_production:
        fb = (settings.frontend_base_url or "").strip()
        ab = (settings.api_public_base_url or "").strip()
        if not fb or "localhost" in fb or "127.0.0.1" in fb or "0.0.0.0" in fb:
            issues.append(
                f"FRONTEND_BASE_URL points to localhost/missing. Set it to your deployed SPA URL (current effective: {frontend_base_url()})."
            )
        if not ab or "localhost" in ab or "127.0.0.1" in ab or "0.0.0.0" in ab:
            issues.append(
                f"API_PUBLIC_BASE_URL points to localhost/missing. Set it to your deployed API URL (current effective: {api_public_base_url()})."
            )
    if settings.is_production and is_mock_allowed():
        issues.append("PAYMENT_ALLOW_MOCK must be false in production.")
    if not is_gateway_configured():
        issues.append("Payment gateway not configured (Pesapal or MTN MoMo keys).")
    elif not gw.get("live_payments"):
        issues.append("Payments unavailable — configure Pesapal or MTN MoMo and disable mock mode.")
    elif gw.get("provider_sandbox"):
        warnings.append(f"Payment provider is in {gw.get('mode')} mode — use live credentials for production money.")
    if not (settings.sui_treasury_address or "").strip():
        warnings.append("SUI_TREASURY_ADDRESS unset — on-chain Sui rent payments disabled.")
    if not (settings.secret_key or "").strip() or settings.secret_key == "change-me-in-production-use-long-random-string":
        issues.append("SECRET_KEY must be a strong random value in production.")
    if settings.is_production and not cloudinary_storage_service.is_cloudinary_configured():
        issues.append(
            "CLOUDINARY_* not configured — property images/videos will fail (local /uploads is not persistent on Vercel)."
        )
    if not privy_token_service.is_privy_configured() and not (settings.firebase_credentials_path or "").strip():
        warnings.append("Neither Privy nor Firebase configured for social login.")
    if not walrus_service.is_walrus_configured():
        warnings.append(
            "WALRUS_PUBLISHER_URL unset — proofs use SHA-256 content hashes only (still verifiable)."
        )
    if not chain.get("package_id"):
        warnings.append("SUI_PACKAGE_ID unset — Move contracts not linked (escrow metadata still in DB).")

    ready = len(issues) == 0
    return {
        "ready_for_global_demo": ready and gw.get("live_payments", False),
        "environment": settings.environment,
        "issues": issues,
        "warnings": warnings,
        "payments": gw,
        "blockchain": chain,
        "walrus_live": walrus_service.is_walrus_configured(),
        "privy_configured": privy_token_service.is_privy_configured(),
    }
