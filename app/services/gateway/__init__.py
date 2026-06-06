from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider
from app.services.gateway.config import (
    active_provider_name,
    assert_live_gateway_ready,
    is_mock_allowed,
    is_mtn_momo_configured,
    is_pesapal_configured,
)
from app.services.gateway.flutterwave_provider import FlutterwaveGatewayProvider
from app.services.gateway.mock_provider import MockGatewayProvider
from app.services.gateway.mtn_momo_provider import MtnMomoGatewayProvider
from app.services.gateway.pesapal_provider import PesapalGatewayProvider

_MTN_METHODS = frozenset({"mtn_momo", "mtn", "mobile_money"})
_PESAPAL_METHODS = frozenset({"airtel", "pesapal", "card", "visa", "mastercard"})


def get_gateway_provider() -> PaymentGatewayProvider:
    """
    Uganda rent collection:
    - mtn_momo (default): MTN MoMo Collection API — USSD prompt on tenant phone
    - pesapal: hosted page — MTN, Airtel, card (recommended if you need Airtel + card)
    - flutterwave: optional (not available for all UG merchant signups)
    - mock: local dev only (PAYMENT_ALLOW_MOCK=true)
    """
    if is_mock_allowed() and active_provider_name() == "mock":
        return MockGatewayProvider()

    assert_live_gateway_ready()
    name = active_provider_name()

    if name == "pesapal":
        return PesapalGatewayProvider()
    if name == "flutterwave":
        return FlutterwaveGatewayProvider()
    return MtnMomoGatewayProvider()


def get_gateway_provider_for_method(payment_method: str) -> PaymentGatewayProvider:
    """
    Route checkout to the right provider per method:
    - MTN → MoMo Collection API when configured (in-app USSD, no Pesapal page)
    - Airtel / card → Pesapal hosted checkout when configured
    Falls back to active PAYMENT_GATEWAY_PROVIDER when only one integration is set up.
    """
    if is_mock_allowed() and active_provider_name() == "mock":
        return MockGatewayProvider()

    method = (payment_method or "mtn_momo").strip().lower()
    if method in ("card", "visa", "mastercard"):
        method = "pesapal"

    if method in _MTN_METHODS and is_mtn_momo_configured():
        return MtnMomoGatewayProvider()

    if method in _PESAPAL_METHODS and is_pesapal_configured():
        return PesapalGatewayProvider()

    assert_live_gateway_ready()
    return get_gateway_provider()
