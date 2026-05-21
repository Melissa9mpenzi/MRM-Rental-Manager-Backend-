import json
import re
import secrets
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment_checkout import CheckoutStatus, PaymentCheckout
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.payment_gateway import CheckoutNextAction, CheckoutOut, InitiateCheckoutBody
from app.services import payment_service
from app.services.gateway import get_gateway_provider
from app.services.gateway.config import (
    active_provider_name,
    assert_live_gateway_ready,
    gateway_public_status,
    is_mock_allowed,
)
from app.services.gateway.flutterwave_provider import FlutterwaveGatewayProvider
from app.services.gateway.mtn_momo_provider import MtnMomoGatewayProvider
from app.services.gateway.pesapal_provider import PesapalGatewayProvider
from app.utils.response import error_response


MOMO_METHODS = {"mtn_momo", "airtel", "mobile_money"}


def _normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw.strip())
    if digits.startswith("256"):
        return digits
    if digits.startswith("0") and len(digits) >= 10:
        return "256" + digits[1:]
    if len(digits) == 9:
        return "256" + digits
    return digits or None


def _checkout_out(checkout: PaymentCheckout, next_action: CheckoutNextAction) -> dict:
    return CheckoutOut(
        reference=checkout.reference,
        status=checkout.status.value,
        provider=checkout.provider,
        amount=float(checkout.amount),
        currency=checkout.currency,
        payment_method=checkout.payment_method,
        invoice_id=checkout.invoice_id,
        next_action=next_action,
        payment_id=checkout.payment_id,
    ).model_dump()


def initiate_checkout(db: Session, user: User, body: InitiateCheckoutBody) -> dict:
    tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
    if not tenant:
        raise error_response("Tenant profile not found.", status_code=404)

    invoice = (
        db.query(Invoice)
        .filter(
            Invoice.id == body.invoice_id,
            Invoice.tenant_id == tenant.id,
            Invoice.is_deleted == False,
        )
        .first()
    )
    if not invoice:
        raise error_response("Invoice not found.", status_code=404)

    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.cancelled):
        raise error_response(f"Invoice is already {invoice.status.value}.", status_code=409)

    balance = Decimal(str(invoice.balance_due))
    if balance <= 0:
        raise error_response("Nothing due on this invoice.", status_code=400)

    amount = Decimal(str(body.amount)) if body.amount is not None else balance
    if amount <= 0 or amount > balance:
        raise error_response(f"Amount must be between 0 and {balance}.", status_code=400)

    method = (body.payment_method or "mtn_momo").strip().lower()
    if method in ("card", "visa"):
        method = "other"
    phone = _normalize_phone(body.phone or tenant.phone)

    if method in MOMO_METHODS and not phone:
        raise error_response("Phone number is required for Mobile Money (256…).", status_code=400)

    assert_live_gateway_ready()
    gw_name = active_provider_name()

    if gw_name == "mtn_momo" and method == "airtel":
        raise error_response(
            "Airtel Money requires Pesapal. Set PAYMENT_GATEWAY_PROVIDER=pesapal in API .env, "
            "or pay with MTN MoMo.",
            status_code=400,
        )
    if gw_name == "mtn_momo" and method not in ("mtn_momo", "mtn", "mobile_money"):
        raise error_response("This server uses MTN MoMo API for MTN only. Use Pesapal for Airtel/card.", status_code=400)

    reference = f"rd_{uuid.uuid4().hex[:24]}"
    provider = get_gateway_provider()
    redirect_url = (
        f"{settings.frontend_base_url.rstrip('/')}/tenant/pay?checkout={reference}&status=return"
    )
    if settings.environment == "production" and not redirect_url.startswith("https://"):
        raise error_response(
            "FRONTEND_BASE_URL must use HTTPS in production for payment redirects.",
            status_code=503,
        )

    checkout = PaymentCheckout(
        reference=reference,
        provider=provider.name,
        status=CheckoutStatus.pending,
        tenant_id=tenant.id,
        invoice_id=invoice.id,
        owner_id=invoice.owner_id,
        amount=amount,
        currency="UGX",
        payment_method=method,
        phone=phone,
        payer_email=tenant.email or user.email,
    )
    db.add(checkout)
    db.flush()

    try:
        init = provider.initiate(
            reference=reference,
            amount=amount,
            currency="UGX",
            payment_method=method,
            phone=phone,
            email=checkout.payer_email,
            title=f"Rent {invoice.invoice_number}",
            redirect_url=redirect_url,
        )
    except ValueError as exc:
        db.rollback()
        raise error_response(str(exc), status_code=503) from exc
    except Exception as exc:
        db.rollback()
        raise error_response(f"Payment provider error: {exc}", status_code=502) from exc

    checkout.status = CheckoutStatus.processing
    checkout.provider_tx_id = init.provider_tx_id
    checkout.provider_link = init.payment_link
    checkout.provider_payload = json.dumps(init.raw or {})[:8000]

    if provider.name == "pesapal" and not init.payment_link:
        db.rollback()
        raise error_response("Pesapal did not return a payment URL.", status_code=502)

    next_action = CheckoutNextAction(
        type=init.next_action_type,
        message=init.message,
        payment_link=init.payment_link,
        simulate_url=None,
    )
    db.commit()
    db.refresh(checkout)
    return _checkout_out(checkout, next_action)


def _resolve_checkout_reference(db: Session, ref: str) -> Optional[str]:
    if ref.startswith("rd_"):
        return ref
    row = (
        db.query(PaymentCheckout)
        .filter(PaymentCheckout.provider_tx_id == ref)
        .first()
    )
    return row.reference if row else None


def try_settle_from_provider(db: Session, checkout: PaymentCheckout) -> Optional[PaymentCheckout]:
    """Poll provider APIs — settle only after confirmed success."""
    if checkout.status == CheckoutStatus.completed:
        return checkout

    status, tx_id, raw = "processing", None, None
    ref = checkout.reference

    if checkout.provider == "mtn_momo" and checkout.provider_tx_id:
        status, tx_id, raw = MtnMomoGatewayProvider().verify_by_reference(checkout.provider_tx_id)
    elif checkout.provider == "pesapal":
        status, tx_id, raw = PesapalGatewayProvider().verify_by_merchant_reference(
            checkout.provider_tx_id or checkout.reference
        )
    elif checkout.provider == "flutterwave":
        status, tx_id, raw = FlutterwaveGatewayProvider().verify_by_reference(checkout.reference)
    else:
        return None

    if status == "completed":
        return complete_checkout(db, ref, provider_tx_id=tx_id, provider_payload=raw)
    if status == "failed":
        return complete_checkout(
            db,
            ref,
            provider_tx_id=tx_id,
            provider_payload=raw,
            failure_reason="Payment failed or was cancelled.",
            mark_failed=True,
        )
    return None


def get_checkout(db: Session, user: User, reference: str) -> dict:
    checkout = db.query(PaymentCheckout).filter(PaymentCheckout.reference == reference).first()
    if not checkout:
        raise error_response("Checkout not found.", status_code=404)

    if checkout.status == CheckoutStatus.processing:
        updated = try_settle_from_provider(db, checkout)
        if updated:
            checkout = updated

    if user.role.value == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        if not tenant or checkout.tenant_id != tenant.id:
            raise error_response("Access denied.", status_code=403)
    elif user.role.value != UserRole.system_admin.value and checkout.owner_id != user.id:
        raise error_response("Access denied.", status_code=403)

    next_action = CheckoutNextAction(
        type="redirect" if checkout.provider_link else "status",
        message=checkout.failure_reason,
        payment_link=checkout.provider_link,
    )
    return _checkout_out(checkout, next_action)


def complete_checkout(
    db: Session,
    reference: str,
    *,
    provider_tx_id: Optional[str] = None,
    provider_payload: Optional[dict[str, Any]] = None,
    failure_reason: Optional[str] = None,
    mark_failed: bool = False,
) -> PaymentCheckout:
    checkout = (
        db.query(PaymentCheckout)
        .filter(PaymentCheckout.reference == reference)
        .with_for_update()
        .first()
    )
    if not checkout:
        raise error_response("Checkout not found.", status_code=404)

    if checkout.status == CheckoutStatus.completed:
        return checkout

    if mark_failed:
        checkout.status = CheckoutStatus.failed
        checkout.failure_reason = failure_reason or "Payment failed"
        checkout.provider_payload = json.dumps(provider_payload or {})[:8000]
        db.commit()
        return checkout

    invoice = db.query(Invoice).filter(Invoice.id == checkout.invoice_id).first()
    if not invoice:
        raise error_response("Invoice not found.", status_code=404)

    api_method = checkout.payment_method
    if api_method == "other" and checkout.provider == "flutterwave":
        api_method = "other"

    payment = payment_service.settle_invoice_payment(
        db,
        invoice,
        amount=Decimal(str(checkout.amount)),
        payment_method=api_method,
        reference=provider_tx_id or checkout.provider_tx_id or reference,
        notes=f"Online via {checkout.provider}",
    )

    checkout.status = CheckoutStatus.completed
    checkout.payment_id = payment.id
    checkout.provider_tx_id = provider_tx_id or checkout.provider_tx_id
    checkout.completed_at = datetime.now(timezone.utc)
    if provider_payload:
        checkout.provider_payload = json.dumps(provider_payload)[:8000]
    db.commit()
    db.refresh(checkout)
    return checkout


def handle_provider_webhook(
    db: Session,
    provider_name: str,
    headers: dict[str, str],
    body: bytes,
) -> dict:
    if provider_name == "mock":
        if not is_mock_allowed():
            raise error_response("Mock webhooks are disabled.", status_code=404)
        from app.services.gateway.mock_provider import MockGatewayProvider

        provider = MockGatewayProvider()
    elif provider_name in ("mtn-momo", "mtn_momo"):
        provider = MtnMomoGatewayProvider()
    elif provider_name == "pesapal":
        provider = PesapalGatewayProvider()
    elif provider_name == "flutterwave":
        provider = FlutterwaveGatewayProvider()
    else:
        raise error_response("Unknown payment provider.", status_code=404)

    if not provider.verify_webhook(headers, body):
        raise error_response("Invalid webhook signature.", status_code=401)

    try:
        payload = json.loads(body.decode() or "{}")
    except json.JSONDecodeError:
        raise error_response("Invalid JSON body.", status_code=400)

    reference, status, tx_id, reason = provider.parse_webhook(payload)
    if not reference:
        return {"ok": True, "ignored": True}

    resolved = _resolve_checkout_reference(db, reference) or reference

    if status == "completed":
        complete_checkout(db, resolved, provider_tx_id=tx_id, provider_payload=payload)
    elif status == "failed":
        complete_checkout(
            db,
            resolved,
            provider_tx_id=tx_id,
            provider_payload=payload,
            failure_reason=reason,
            mark_failed=True,
        )

    return {"ok": True, "reference": resolved, "status": status}


def simulate_checkout(db: Session, reference: str, user: Optional[User] = None) -> dict:
    if not is_mock_allowed():
        raise error_response(
            "Simulated payments are disabled. Configure MTN MoMo or Pesapal for real checkout.",
            status_code=403,
        )

    if user and user.role.value == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        pending = db.query(PaymentCheckout).filter(PaymentCheckout.reference == reference).first()
        if not pending or not tenant or pending.tenant_id != tenant.id:
            raise error_response("Access denied.", status_code=403)

    checkout = complete_checkout(
        db,
        reference,
        provider_tx_id=f"mock_sim_{secrets.token_hex(6)}",
        provider_payload={"simulated": True},
    )
    return _checkout_out(
        checkout,
        CheckoutNextAction(type="completed", message="Payment recorded automatically."),
    )
