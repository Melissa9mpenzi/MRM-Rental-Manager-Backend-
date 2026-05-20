from app.config import settings
from app.services.gateway.base import PaymentGatewayProvider
from app.services.gateway.config import active_provider_name, assert_live_gateway_ready, is_mock_allowed
from app.services.gateway.flutterwave_provider import FlutterwaveGatewayProvider
from app.services.gateway.mock_provider import MockGatewayProvider
from app.services.gateway.mtn_momo_provider import MtnMomoGatewayProvider
from app.services.gateway.pesapal_provider import PesapalGatewayProvider


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
