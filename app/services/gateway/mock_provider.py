import json
from decimal import Decimal
from typing import Any, Optional

from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider, ProviderInitResult


class MockGatewayProvider(PaymentGatewayProvider):
    name = "mock"

    def initiate(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: str,
        payment_method: str,
        phone: Optional[str],
        email: Optional[str],
        title: str,
        redirect_url: str,
    ) -> ProviderInitResult:
        method_label = payment_method.replace("_", " ").title()
        msg = (
            f"Mock {method_label}: approve UGX {amount:,.0f} on {phone or 'your phone'}. "
            f"In development, call POST .../checkout/{reference}/simulate to auto-settle."
        )
        simulate = f"{settings.api_public_base_url.rstrip('/')}/api/v1/payments/checkout/{reference}/simulate"
        return ProviderInitResult(
            provider_tx_id=f"mock_{reference}",
            payment_link=None,
            next_action_type="ussd_prompt",
            message=msg,
            raw={"simulate_url": simulate, "redirect_url": redirect_url},
        )

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (settings.payment_webhook_secret or "").strip()
        if not secret:
            return settings.environment != "production"
        return headers.get("x-rentdirect-webhook-secret") == secret

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, str, Optional[str], Optional[str]]:
        ref = payload.get("reference") or payload.get("tx_ref") or ""
        status = (payload.get("status") or "completed").lower()
        tx = payload.get("provider_tx_id") or payload.get("transaction_id")
        reason = payload.get("failure_reason")
        return str(ref), status, tx, reason
