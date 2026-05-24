"""
Sui wallet payments — hybrid with MoMo/Pesapal (does not replace fiat gateways).

Tenant signs a SUI transfer to platform treasury; backend verifies tx digest on-chain.
"""
from decimal import Decimal
from typing import Any, Optional

from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider, ProviderInitResult
from app.services.blockchain.sui_rpc import ugx_to_mist


class SuiGatewayProvider(PaymentGatewayProvider):
    name = "sui"

    def _treasury(self) -> str:
        addr = (settings.sui_treasury_address or "").strip()
        if not addr:
            raise ValueError(
                "SUI_TREASURY_ADDRESS is required for wallet payments. "
                "Fund a devnet address and set it in .env."
            )
        return addr

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
        if payment_method not in ("sui", "crypto", "blockchain"):
            raise ValueError("Sui gateway only supports payment_method sui.")

        amount_mist = ugx_to_mist(amount)
        if amount_mist < 1_000_000:
            amount_mist = 1_000_000  # min ~0.001 SUI for devnet demos

        return ProviderInitResult(
            provider_tx_id=None,
            payment_link=None,
            next_action_type="sui_sign",
            message="Sign the SUI payment in your wallet (Slush, Nightly, Suiet, etc.).",
            raw={
                "network": (settings.sui_network or "devnet").lower(),
                "treasury_address": self._treasury(),
                "amount_mist": amount_mist,
                "amount_ugx": str(int(amount)) if amount == int(amount) else str(amount),
                "reference": reference,
                "title": title[:100],
                "package_id": (settings.sui_package_id or "").strip() or None,
                "escrow_enabled": bool((settings.sui_package_id or "").strip()),
            },
        )

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return False

    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, str, Optional[str], Optional[str]]:
        return "", "processing", None, None
