"""
MTN MoMo Collection API — Uganda (and other MTN markets via TARGET_ENVIRONMENT).

Register: https://momodeveloper.mtn.com
Products: Collection → RequestToPay (USSD prompt on customer's phone).
"""
import base64
import json
import uuid
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider, ProviderInitResult


class MtnMomoGatewayProvider(PaymentGatewayProvider):
    name = "mtn_momo"

    def _base_url(self) -> str:
        return (settings.mtn_momo_base_url or "https://sandbox.momodeveloper.mtn.com").rstrip("/")

    def _subscription_key(self) -> str:
        key = (settings.mtn_momo_subscription_key or "").strip()
        if not key:
            raise ValueError(
                "MTN_MOMO_SUBSCRIPTION_KEY is required. Create an app at https://momodeveloper.mtn.com "
                "and subscribe to the Collection product."
            )
        return key

    def _access_token(self) -> str:
        user = (settings.mtn_momo_api_user or "").strip()
        api_key = (settings.mtn_momo_api_key or "").strip()
        if not user or not api_key:
            raise ValueError(
                "MTN_MOMO_API_USER and MTN_MOMO_API_KEY are required (provision API user in MoMo developer portal)."
            )
        cred = base64.b64encode(f"{user}:{api_key}".encode()).decode()
        headers = {
            "Authorization": f"Basic {cred}",
            "Ocp-Apim-Subscription-Key": self._subscription_key(),
        }
        with httpx.Client(timeout=30.0) as client:
            res = client.post(f"{self._base_url()}/collection/token/", headers=headers)
            res.raise_for_status()
            data = res.json()
        token = data.get("access_token")
        if not token:
            raise ValueError("MTN MoMo token response missing access_token")
        return token

    def _collection_headers(self, reference_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "X-Reference-Id": reference_id,
            "X-Target-Environment": (settings.mtn_momo_target_environment or "sandbox").strip(),
            "Ocp-Apim-Subscription-Key": self._subscription_key(),
            "Content-Type": "application/json",
        }

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
        if payment_method not in ("mtn_momo", "mtn", "mobile_money"):
            raise ValueError("MTN MoMo gateway only supports payment_method mtn_momo.")

        if not phone:
            raise ValueError("Phone number (256…) is required for MTN MoMo.")

        momo_ref = str(uuid.uuid4())
        body = {
            "amount": str(int(amount)) if amount == int(amount) else str(amount),
            "currency": currency or "UGX",
            "externalId": reference[:50],
            "payer": {
                "partyIdType": "MSISDN",
                "partyId": phone,
            },
            "payerMessage": title[:160] or "Rent payment",
            "payeeNote": f"RentDirect {reference[:40]}",
        }
        callback = (settings.mtn_momo_callback_url or "").strip()
        if callback:
            body["payerMessage"] = body["payerMessage"]

        headers = self._collection_headers(momo_ref)
        with httpx.Client(timeout=45.0) as client:
            res = client.post(
                f"{self._base_url()}/collection/v1_0/requesttopay",
                headers=headers,
                json=body,
            )
            if res.status_code not in (200, 201, 202):
                try:
                    err = res.json()
                except Exception:
                    err = res.text
                raise ValueError(f"MTN RequestToPay failed ({res.status_code}): {err}")

        return ProviderInitResult(
            provider_tx_id=momo_ref,
            payment_link=None,
            next_action_type="ussd_prompt",
            message=(
                "Check your MTN phone — approve the MoMo prompt (PIN) to pay. "
                "We record the payment when MTN confirms."
            ),
            raw={"momo_reference_id": momo_ref, "external_id": reference},
        )

    def verify_by_reference(self, momo_reference_id: str) -> tuple[str, Optional[str], Optional[dict[str, Any]]]:
        """Poll MTN for RequestToPay status."""
        if not momo_reference_id:
            return "processing", None, None
        headers = self._collection_headers(momo_reference_id)
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{self._base_url()}/collection/v1_0/requesttopay/{momo_reference_id}",
                headers=headers,
            )
            if res.status_code == 404:
                return "processing", None, None
            res.raise_for_status()
            data = res.json()

        status = (data.get("status") or "").upper()
        if status == "SUCCESSFUL":
            return "completed", data.get("financialTransactionId") or momo_reference_id, data
        if status in ("FAILED", "CANCELLED", "TIMEOUT"):
            reason = data.get("reason") or status
            return "failed", None, data
        return "processing", None, data

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (settings.mtn_momo_webhook_secret or "").strip()
        if not secret:
            return settings.environment != "production"
        return headers.get("x-mtn-signature") == secret or headers.get("authorization") == secret

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, str, Optional[str], Optional[str]]:
        """
        Map callback to checkout. externalId is our rd_* reference when MTN echoes it;
        otherwise match via financialTransactionId stored on checkout.
        """
        ref = (
            payload.get("externalId")
            or payload.get("external_id")
            or payload.get("referenceId")
            or ""
        )
        status_raw = (payload.get("status") or "").upper()
        tx = payload.get("financialTransactionId") or payload.get("transactionId")

        if status_raw == "SUCCESSFUL":
            return str(ref), "completed", str(tx) if tx else None, None
        if status_raw in ("FAILED", "CANCELLED", "TIMEOUT"):
            return str(ref), "failed", None, payload.get("reason") or status_raw
        return str(ref), "processing", None, None
