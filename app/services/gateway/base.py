from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional


@dataclass
class ProviderInitResult:
    provider_tx_id: Optional[str]
    payment_link: Optional[str]
    next_action_type: str  # ussd_prompt | redirect
    message: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


class PaymentGatewayProvider(ABC):
    name: str

    @abstractmethod
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
        ...

    @abstractmethod
    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        ...

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> tuple[str, str, Optional[str], Optional[str]]:
        """
        Returns (reference, status, provider_tx_id, failure_reason).
        status: completed | failed | processing
        """
