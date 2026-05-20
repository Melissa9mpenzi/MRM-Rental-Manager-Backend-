"""
Pesapal API 3 — Uganda-friendly aggregator (MTN, Airtel, card).

Docs: https://developer.pesapal.com/
"""
import uuid
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider, ProviderInitResult


class PesapalGatewayProvider(PaymentGatewayProvider):
    name = "pesapal"

    def _base(self) -> str:
        if (settings.pesapal_env or "sandbox").lower() == "live":
            return "https://pay.pesapal.com/v3"
        return "https://cybqa.pesapal.com/pesapalv3"

    def _token(self) -> str:
        key = (settings.pesapal_consumer_key or "").strip()
        secret = (settings.pesapal_consumer_secret or "").strip()
        if not key or not secret:
            raise ValueError(
                "PESAPAL_CONSUMER_KEY and PESAPAL_CONSUMER_SECRET are required. "
                "Sign up at https://www.pesapal.com/ug/business/online/"
            )
        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                f"{self._base()}/api/Auth/RequestToken",
                json={"consumer_key": key, "consumer_secret": secret},
            )
            res.raise_for_status()
            data = res.json()
        token = data.get("token")
        if not token:
            raise ValueError("Pesapal auth failed")
        return token

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
        token = self._token()
        order_id = reference[:50]
        payload = {
            "id": order_id,
            "currency": currency or "UGX",
            "amount": float(amount),
            "description": title[:100] or "Rent payment",
            "callback_url": redirect_url,
            "redirect_mode": "TOP_WINDOW",
            "notification_id": (settings.pesapal_ipn_id or "").strip() or None,
            "billing_address": {
                "email_address": email or "tenant@rentdirect.local",
                "phone_number": phone or "",
                "country_code": "UG",
            },
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        with httpx.Client(timeout=45.0) as client:
            res = client.post(
                f"{self._base()}/api/Transactions/SubmitOrderRequest",
                headers=headers,
                json=payload,
            )
            res.raise_for_status()
            data = res.json()

        link = (data.get("redirect_url") or data.get("redirectUrl") or "").strip()
        if not link:
            raise ValueError(data.get("message") or "Pesapal did not return a payment URL")

        tracking = data.get("order_tracking_id") or data.get("orderTrackingId") or str(uuid.uuid4())

        return ProviderInitResult(
            provider_tx_id=str(tracking),
            payment_link=link,
            next_action_type="redirect",
            message="Pay with MTN MoMo, Airtel Money, or card on the secure Pesapal page.",
            raw=data,
        )

    def verify_by_merchant_reference(self, merchant_reference: str) -> tuple[str, Optional[str], Optional[dict]]:
        token = self._token()
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{self._base()}/api/Transactions/GetTransactionStatus",
                headers=headers,
                params={"orderTrackingId": merchant_reference},
            )
            if res.status_code == 404:
                return "processing", None, None
            res.raise_for_status()
            data = res.json()

        status = (data.get("payment_status_description") or data.get("status") or "").lower()
        if status in ("completed", "paid", "success"):
            return "completed", merchant_reference, data
        if status in ("failed", "invalid", "cancelled"):
            return "failed", None, data
        return "processing", None, data

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return True

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, str, Optional[str], Optional[str]]:
        ref = payload.get("order_notification", {}).get("merchant_reference") if isinstance(
            payload.get("order_notification"), dict
        ) else payload.get("MerchantReference") or payload.get("merchant_reference") or ""
        status = (payload.get("status") or payload.get("payment_status") or "").lower()
        if status in ("completed", "paid", "200"):
            return str(ref), "completed", None, None
        if status in ("failed", "cancelled"):
            return str(ref), "failed", None, payload.get("message")
        return str(ref), "processing", None, None
