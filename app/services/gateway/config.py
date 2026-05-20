"""Payment gateway configuration — Uganda: MTN MoMo API or Pesapal."""
from app.config import settings


def is_mock_allowed() -> bool:
    return bool(settings.payment_allow_mock) and settings.environment != "production"


def active_provider_name() -> str:
    return (settings.payment_gateway_provider or "mtn_momo").strip().lower()


def is_mtn_momo_configured() -> bool:
    return bool(
        (settings.mtn_momo_subscription_key or "").strip()
        and (settings.mtn_momo_api_user or "").strip()
        and (settings.mtn_momo_api_key or "").strip()
    )


def is_pesapal_configured() -> bool:
    return bool(
        (settings.pesapal_consumer_key or "").strip()
        and (settings.pesapal_consumer_secret or "").strip()
    )


def is_flutterwave_configured() -> bool:
    return bool((settings.flutterwave_secret_key or "").strip())


def is_gateway_configured() -> bool:
    name = active_provider_name()
    if name == "mock":
        return is_mock_allowed()
    if name == "pesapal":
        return is_pesapal_configured()
    if name == "flutterwave":
        return is_flutterwave_configured()
    return is_mtn_momo_configured()


def gateway_mode() -> str:
    """sandbox | live | unconfigured"""
    name = active_provider_name()
    if name == "mtn_momo":
        env = (settings.mtn_momo_target_environment or "sandbox").lower()
        return "live" if env not in ("sandbox", "mtnghana", "") else "sandbox"
    if name == "pesapal":
        return "live" if (settings.pesapal_env or "").lower() == "live" else "sandbox"
    if name == "flutterwave":
        key = (settings.flutterwave_secret_key or "")
        if not key:
            return "unconfigured"
        return "test" if "TEST" in key.upper() else "live"
    return "unconfigured"


def gateway_public_status() -> dict:
    mock = is_mock_allowed()
    name = active_provider_name()
    configured = is_gateway_configured()
    mode = gateway_mode() if configured else "unconfigured"
    return {
        "provider": name,
        "configured": configured or mock,
        "mode": mode,
        "live_payments": configured and mode == "live" and not mock,
        "mock_enabled": mock,
        "country": "UG",
        "supports": {
            "mtn_momo": name in ("mtn_momo", "pesapal", "mock"),
            "airtel": name in ("pesapal", "mock"),
            "card": name in ("pesapal", "flutterwave", "mock"),
        },
        "requires_webhook_https": settings.environment == "production",
        "setup_hint": _setup_hint(name, configured, mock),
    }


def _setup_hint(name: str, configured: bool, mock: bool) -> str:
    if mock and not configured:
        return "Dev mock mode — not real money."
    if configured:
        return f"Using {name} ({gateway_mode()})."
    if name == "mtn_momo":
        return "Add MTN MoMo Collection keys from https://momodeveloper.mtn.com"
    if name == "pesapal":
        return "Add Pesapal keys from https://www.pesapal.com/ug/business/online/"
    return "Set PAYMENT_GATEWAY_PROVIDER and provider credentials in .env"


def assert_live_gateway_ready() -> None:
    if is_mock_allowed() and active_provider_name() == "mock":
        return
    if not is_gateway_configured():
        name = active_provider_name()
        if name == "mtn_momo":
            raise ValueError(
                "MTN MoMo is not configured. Set MTN_MOMO_SUBSCRIPTION_KEY, MTN_MOMO_API_USER, "
                "and MTN_MOMO_API_KEY from https://momodeveloper.mtn.com (Collection product)."
            )
        if name == "pesapal":
            raise ValueError(
                "Pesapal is not configured. Set PESAPAL_CONSUMER_KEY and PESAPAL_CONSUMER_SECRET "
                "from https://www.pesapal.com/ug/business/online/"
            )
        raise ValueError(
            f"Payment provider '{name}' is not configured. See docs/PAYMENT_GATEWAY.md"
        )
