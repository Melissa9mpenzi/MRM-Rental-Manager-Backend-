import hashlib
import json
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider, ProviderInitResult


class FlutterwaveGatewayProvider(PaymentGatewayProvider):
    name = "flutterwave"
    API_BASE = "https://api.flutterwave.com/v3"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.flutterwave_secret_key}",
            "Content-Type": "application/json",
        }

    def _payment_options(self, payment_method: str) -> str:
        if payment_method in ("mtn_momo", "airtel", "mobile_money"):
            return "mobilemoneyuganda"
        return "card,mobilemoneyuganda"

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
        if not settings.flutterwave_secret_key:
            raise ValueError("FLUTTERWAVE_SECRET_KEY is not configured")

        payload = {
            "tx_ref": reference,
            "amount": str(amount),
            "currency": currency,
            "redirect_url": redirect_url,
            "payment_options": self._payment_options(payment_method),
            "customer": {
                "email": email or "tenant@rentdirect.local",
                "phonenumber": phone or "",
            },
            "customizations": {
                "title": title[:50],
                "description": f"Rent invoice payment · {reference}",
            },
            "meta": {"payment_method": payment_method},
        }

        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                f"{self.API_BASE}/payments",
                headers=self._headers(),
                json=payload,
            )
            res.raise_for_status()
            data = res.json()

        if data.get("status") != "success":
            raise ValueError(data.get("message") or "Flutterwave payment initiation failed")

        link = (data.get("data") or {}).get("link")
        if not link:
            raise ValueError(
                "Flutterwave did not return a payment link. Check API keys and account activation."
            )
        return ProviderInitResult(
            provider_tx_id=reference,
            payment_link=link,
            next_action_type="redirect",
            message="Complete payment on the secure Flutterwave page (MTN MoMo, Airtel, or card).",
            raw=data,
        )

    def verify_by_reference(self, reference: str) -> tuple[str, Optional[str], Optional[dict[str, Any]]]:
        """
        Confirm payment with Flutterwave before settling (real money check).
        Returns (status, provider_tx_id, raw) where status is completed | failed | processing.
        """
        if not settings.flutterwave_secret_key:
            return "processing", None, None

        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{self.API_BASE}/transactions/verify_by_reference",
                headers=self._headers(),
                params={"tx_ref": reference},
            )
            res.raise_for_status()
            body = res.json()

        if body.get("status") != "success":
            return "processing", None, body

        data = body.get("data") or {}
        st = (data.get("status") or "").lower()
        tx_id = str(data.get("id") or data.get("flw_ref") or "")
        currency = (data.get("currency") or "").upper()

        if st == "successful" and currency in ("", "UGX"):
            return "completed", tx_id or None, body
        if st in ("failed", "cancelled"):
            return "failed", tx_id or None, body
        return "processing", tx_id or None, body

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (settings.flutterwave_secret_key or "").strip()
        if not secret:
            return False
        expected = hashlib.sha256(secret.encode()).hexdigest()
        received = headers.get("verif-hash") or headers.get("flutterwave-verif-hash") or ""
        return received == expected

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, str, Optional[str], Optional[str]]:
        event = payload.get("event") or ""
        data = payload.get("data") or payload
        ref = data.get("tx_ref") or data.get("txRef") or ""
        status_raw = (data.get("status") or "").lower()
        tx_id = str(data.get("id") or data.get("flw_ref") or "")

        if event == "charge.completed" and status_raw == "successful":
            return str(ref), "completed", tx_id or None, None
        if status_raw in ("failed", "cancelled"):
            return str(ref), "failed", tx_id or None, data.get("processor_response") or status_raw
        return str(ref), "processing", tx_id or None, None
