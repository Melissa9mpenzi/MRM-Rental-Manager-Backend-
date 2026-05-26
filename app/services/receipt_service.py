"""Enterprise receipt issuance, verification, PDF, and email delivery."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models.blockchain_receipt import BlockchainReceipt
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentType
from app.models.system_receipt import ReceiptStatus, ReceiptType, SystemReceipt
from app.models.property import Unit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.receipt_pdf import build_receipt_pdf
from app.utils.response import error_response

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

METHOD_PREFIX = {
    "mtn_momo": "MTN",
    "airtel": "ATL",
    "bank": "BNK",
    "cash": "CSH",
    "sui": "SUI",
    "other": "UGX",
}


def _verify_base_url() -> str:
    """Short QR URL — kind resolved server-side from token."""
    base = (settings.frontend_base_url or "http://localhost:5173").rstrip("/")
    return f"{base}/verify"


def _method_prefix(method: Optional[str]) -> str:
    return METHOD_PREFIX.get((method or "other").lower(), "UGX")


def _next_receipt_number(db: Session, method: str, year: int) -> str:
    prefix = _method_prefix(method)
    pattern = f"RDU-{prefix}-{year}-%"
    count = db.query(SystemReceipt).filter(SystemReceipt.receipt_number.like(pattern)).count()
    seq = count + 1
    return f"RDU-{prefix}-{year}-{seq:05d}"


def _period_label(payment: Payment) -> str:
    if payment.period_month and payment.period_year:
        return f"{MONTHS[payment.period_month - 1]} {payment.period_year}"
    return "—"


def _smart_summary(
    *,
    receipt_type: ReceiptType,
    tenant_name: str,
    period: str,
    amount: Decimal,
    currency: str,
    method: str,
    status: ReceiptStatus,
    has_chain: bool,
) -> str:
    amt = f"{currency} {float(amount):,.0f}"
    method_label = method.replace("_", " ").title()
    if status == ReceiptStatus.escrowed:
        return f"Security deposit of {amt} is held in escrow for {tenant_name or 'the tenant'}."
    if receipt_type == ReceiptType.commission:
        return f"Agent commission of {amt} recorded for {period}."
    if receipt_type == ReceiptType.government_tax:
        return f"URA tax receipt for {amt} — compliant with Uganda Revenue Authority requirements."
    chain = " and secured on-chain" if has_chain else ""
    return (
        f"Your {period} rent payment of {amt} via {method_label} was successfully processed{chain}."
    )


def _build_security_fields(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    verification_hash = hashlib.sha256(canonical.encode()).hexdigest()
    checksum = hashlib.sha256(f"{verification_hash}:{settings.secret_key[:16]}".encode()).hexdigest()[:32]
    token = secrets.token_urlsafe(24)
    signature = hashlib.sha256(f"RD-SIGN:{checksum}:{settings.secret_key}".encode()).hexdigest()[:64]
    return token, verification_hash, checksum, signature


def _load_payment_context(db: Session, payment: Payment) -> dict[str, Any]:
    tenant = (
        db.query(Tenant)
        .options(
            joinedload(Tenant.unit).joinedload(Unit.parent_property),
            joinedload(Tenant.owner),
        )
        .filter(Tenant.id == payment.tenant_id)
        .first()
    )
    unit = tenant.unit if tenant else None
    prop = unit.parent_property if unit else None
    landlord = tenant.owner if tenant else None

    invoice = None
    if payment.lease_id:
        invoice = (
            db.query(Invoice)
            .filter(
                Invoice.lease_id == payment.lease_id,
                Invoice.period_month == payment.period_month,
                Invoice.period_year == payment.period_year,
                Invoice.is_deleted == False,  # noqa: E712
            )
            .first()
        )

    pm = payment.payment_method.value if hasattr(payment.payment_method, "value") else str(payment.payment_method)
    pt = payment.payment_type.value if hasattr(payment.payment_type, "value") else str(payment.payment_type)

    return {
        "tenant": tenant,
        "unit": unit,
        "prop": prop,
        "landlord": landlord,
        "invoice": invoice,
        "payment_method": pm,
        "payment_type": pt,
    }


def _receipt_type_from_payment(payment: Payment) -> ReceiptType:
    pt = payment.payment_type
    val = pt.value if hasattr(pt, "value") else str(pt)
    if val == "deposit":
        return ReceiptType.security_deposit
    return ReceiptType.rent_payment


def _receipt_status_from_payment(payment: Payment) -> ReceiptStatus:
    if payment.payment_type == PaymentType.deposit:
        return ReceiptStatus.escrowed
    return ReceiptStatus.paid


def issue_from_payment(
    db: Session,
    payment: Payment,
    *,
    invoice: Optional[Invoice] = None,
    blockchain_receipt: Optional[BlockchainReceipt] = None,
    wallet_address: Optional[str] = None,
    upload_dir: Optional[str] = None,
    send_email: bool = True,
) -> SystemReceipt:
    """Create enterprise receipt after successful payment."""
    existing = db.query(SystemReceipt).filter(SystemReceipt.payment_id == payment.id, SystemReceipt.is_void == False).first()  # noqa: E712
    if existing:
        return existing

    ctx = _load_payment_context(db, payment)
    tenant = ctx["tenant"]
    prop = ctx["prop"]
    unit = ctx["unit"]
    landlord = ctx["landlord"]
    inv = invoice or ctx["invoice"]

    year = datetime.now(timezone.utc).year
    method = ctx["payment_method"]
    receipt_number = _next_receipt_number(db, method, year)
    receipt_type = _receipt_type_from_payment(payment)
    status = _receipt_status_from_payment(payment)

    network = (settings.sui_network or "devnet").lower()
    tx_hash = blockchain_receipt.tx_digest if blockchain_receipt else None
    walrus_id = blockchain_receipt.walrus_blob_id if blockchain_receipt else None
    explorer = None
    if tx_hash:
        explorer = f"https://suiscan.xyz/{network}/tx/{tx_hash}"

    # URA tax stub — configurable later
    vat_rate = Decimal("0")
    vat_amount = None
    tax_id = None
    ura_code = None

    payload = {
        "receipt_number": receipt_number,
        "payment_id": payment.id,
        "amount": str(payment.amount),
        "currency": "UGX",
        "method": method,
        "reference": payment.reference,
        "tenant_id": payment.tenant_id,
        "issued": datetime.now(timezone.utc).isoformat(),
    }
    token, verification_hash, checksum, signature = _build_security_fields(payload)

    period = _period_label(payment)
    has_chain = bool(tx_hash)
    summary = _smart_summary(
        receipt_type=receipt_type,
        tenant_name=tenant.full_name if tenant else "",
        period=period,
        amount=Decimal(str(payment.amount)),
        currency="UGX",
        method=method,
        status=status,
        has_chain=has_chain,
    )

    row = SystemReceipt(
        receipt_number=receipt_number,
        receipt_type=receipt_type,
        status=status,
        payment_id=payment.id,
        invoice_id=inv.id if inv else None,
        blockchain_receipt_id=blockchain_receipt.id if blockchain_receipt else None,
        tenant_id=payment.tenant_id,
        owner_id=payment.owner_id,
        amount=payment.amount,
        currency="UGX",
        payment_method=method,
        transaction_reference=payment.reference,
        tenant_name=tenant.full_name if tenant else None,
        landlord_name=landlord.full_name if landlord else None,
        property_name=prop.name if prop else None,
        property_address=prop.address if prop else None,
        unit_number=unit.unit_number if unit else None,
        lease_start=str(tenant.lease_start) if tenant and tenant.lease_start else None,
        lease_end=str(tenant.lease_end) if tenant and tenant.lease_end else None,
        period_label=period,
        wallet_address=wallet_address,
        tx_hash=tx_hash,
        contract_id=(settings.sui_package_id or None),
        walrus_blob_id=walrus_id,
        explorer_url=explorer,
        tax_id=tax_id,
        ura_compliance_code=ura_code,
        vat_amount=vat_amount,
        tax_percentage=vat_rate,
        verification_token=token,
        verification_hash=verification_hash,
        checksum=checksum,
        digital_signature=signature,
        smart_summary=summary,
        metadata_json=json.dumps(payload),
    )
    db.add(row)
    db.flush()

    if upload_dir:
        pdf_dict = _to_pdf_dict(row, network=network)
        verify_url = f"{_verify_base_url()}/{token}"
        row.pdf_path = build_receipt_pdf(pdf_dict, verify_url=verify_url, upload_dir=upload_dir)

    db.flush()

    if send_email:
        try:
            _send_receipt_email(db, row, tenant)
            row.emailed_at = datetime.now(timezone.utc)
        except Exception:
            pass

    _notify_parties(db, row, tenant, landlord)
    return row


def _to_pdf_dict(row: SystemReceipt, *, network: str) -> dict[str, Any]:
    st = row.status.value if hasattr(row.status, "value") else str(row.status)
    rt = row.receipt_type.value if hasattr(row.receipt_type, "value") else str(row.receipt_type)
    return {
        "receipt_number": row.receipt_number,
        "receipt_type": rt,
        "status": st,
        "amount": float(row.amount),
        "currency": row.currency,
        "amount_display": f"{row.currency} {float(row.amount):,.0f}",
        "payment_method": row.payment_method,
        "transaction_reference": row.transaction_reference,
        "tenant_name": row.tenant_name,
        "landlord_name": row.landlord_name,
        "property_name": row.property_name,
        "property_address": row.property_address,
        "unit_number": row.unit_number,
        "lease_start": row.lease_start,
        "lease_end": row.lease_end,
        "period_label": row.period_label,
        "wallet_address": row.wallet_address,
        "tx_hash": row.tx_hash,
        "contract_id": row.contract_id,
        "walrus_blob_id": row.walrus_blob_id,
        "network": network,
        "tax_id": row.tax_id,
        "ura_compliance_code": row.ura_compliance_code,
        "vat_amount": float(row.vat_amount) if row.vat_amount else None,
        "vat_display": f"UGX {float(row.vat_amount):,.0f}" if row.vat_amount else None,
        "tax_percentage": float(row.tax_percentage) if row.tax_percentage else None,
        "smart_summary": row.smart_summary,
        "checksum": row.checksum,
        "digital_signature": row.digital_signature,
        "issued_at_label": row.issued_at.strftime("%d %B %Y %H:%M UTC") if row.issued_at else "—",
    }


def _notify_parties(db: Session, row: SystemReceipt, tenant: Optional[Tenant], landlord: Optional[User]) -> None:
    try:
        from app.models.notification import Notification, NotifType

        if tenant and tenant.user_id:
            db.add(
                Notification(
                    user_id=tenant.user_id,
                    title="Payment receipt issued",
                    message=f"Receipt {row.receipt_number} for UGX {float(row.amount):,.0f} is ready.",
                    notif_type=NotifType.payment_received,
                    link=f"/tenant/receipts/{row.id}",
                )
            )
        if landlord:
            db.add(
                Notification(
                    user_id=landlord.id,
                    title="Receipt generated",
                    message=f"{row.tenant_name or 'Tenant'} — {row.receipt_number} (UGX {float(row.amount):,.0f}).",
                    notif_type=NotifType.payment_received,
                    link=f"/receipts/{row.id}",
                )
            )
    except Exception:
        pass


def _send_receipt_email(db: Session, row: SystemReceipt, tenant: Optional[Tenant]) -> None:
    from app.services.email_service import send_payment_receipt_email

    to = (tenant.email if tenant else None) or None
    if not to and tenant and tenant.user_id:
        user = db.query(User).filter(User.id == tenant.user_id).first()
        to = user.email if user else None
    if not to:
        return
    verify_url = f"{_verify_base_url()}/{row.verification_token}"
    send_payment_receipt_email(
        to=to,
        receipt_number=row.receipt_number,
        amount_ugx=float(row.amount),
        period=row.period_label or "",
        property_name=row.property_name or "",
        verify_url=verify_url,
        pdf_path=row.pdf_path,
    )


def serialize(row: SystemReceipt) -> dict[str, Any]:
    st = row.status.value if hasattr(row.status, "value") else str(row.status)
    rt = row.receipt_type.value if hasattr(row.receipt_type, "value") else str(row.receipt_type)
    return {
        "id": row.id,
        "receipt_number": row.receipt_number,
        "receipt_type": rt,
        "status": st,
        "amount": float(row.amount),
        "currency": row.currency,
        "payment_method": row.payment_method,
        "transaction_reference": row.transaction_reference,
        "tenant_name": row.tenant_name,
        "landlord_name": row.landlord_name,
        "property_name": row.property_name,
        "property_address": row.property_address,
        "unit_number": row.unit_number,
        "period_label": row.period_label,
        "wallet_address": row.wallet_address,
        "tx_hash": row.tx_hash,
        "contract_id": row.contract_id,
        "walrus_blob_id": row.walrus_blob_id,
        "explorer_url": row.explorer_url,
        "tax_id": row.tax_id,
        "ura_compliance_code": row.ura_compliance_code,
        "vat_amount": float(row.vat_amount) if row.vat_amount else None,
        "tax_percentage": float(row.tax_percentage) if row.tax_percentage else None,
        "verification_token": row.verification_token,
        "verification_url": f"{_verify_base_url()}/{row.verification_token}",
        "pdf_url": row.pdf_path,
        "smart_summary": row.smart_summary,
        "payment_id": row.payment_id,
        "invoice_id": row.invoice_id,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "checksum": row.checksum,
        "digital_signature": row.digital_signature,
    }


def list_for_user(
    db: Session,
    user: User,
    *,
    receipt_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    q = db.query(SystemReceipt).filter(SystemReceipt.is_void == False)  # noqa: E712

    if user.role == UserRole.system_admin:
        pass
    elif user.role == UserRole.tenant:
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        if not tenant:
            return []
        q = q.filter(SystemReceipt.tenant_id == tenant.id)
    else:
        q = q.filter(SystemReceipt.owner_id == user.id)

    if receipt_type:
        q = q.filter(SystemReceipt.receipt_type == receipt_type)
    if status:
        q = q.filter(SystemReceipt.status == status)

    rows = q.order_by(SystemReceipt.issued_at.desc()).limit(limit).offset(offset).all()
    return [serialize(r) for r in rows]


def get_for_user(db: Session, receipt_id: int, user: User) -> dict:
    row = db.query(SystemReceipt).filter(SystemReceipt.id == receipt_id, SystemReceipt.is_void == False).first()  # noqa: E712
    if not row:
        raise error_response("Receipt not found.", status_code=404)
    if not _can_access(user, row, db):
        raise error_response("Access denied.", status_code=403)
    return serialize(row)


def _can_access(user: User, row: SystemReceipt, db: Session) -> bool:
    if user.role == UserRole.system_admin:
        return True
    if user.role == UserRole.tenant:
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        return tenant is not None and row.tenant_id == tenant.id
    return row.owner_id == user.id


def verify_public(db: Session, token: str) -> dict:
    from app.services import verification_service

    return verification_service.verify_receipt(db, token)


def ensure_pdf(db: Session, row: SystemReceipt, upload_dir: str) -> str:
    if row.pdf_path:
        return row.pdf_path
    network = (settings.sui_network or "devnet").lower()
    pdf_dict = _to_pdf_dict(row, network=network)
    verify_url = f"{_verify_base_url()}/{row.verification_token}"
    row.pdf_path = build_receipt_pdf(pdf_dict, verify_url=verify_url, upload_dir=upload_dir)
    db.commit()
    return row.pdf_path


def email_receipt(db: Session, receipt_id: int, user: User, to_email: Optional[str] = None) -> None:
    row = db.query(SystemReceipt).filter(SystemReceipt.id == receipt_id).first()
    if not row:
        raise error_response("Receipt not found.", status_code=404)
    if not _can_access(user, row, db):
        raise error_response("Access denied.", status_code=403)
    tenant = db.query(Tenant).filter(Tenant.id == row.tenant_id).first() if row.tenant_id else None
    if to_email:
        from app.services.email_service import send_payment_receipt_email

        verify_url = f"{_verify_base_url()}/{row.verification_token}"
        send_payment_receipt_email(
            to=to_email,
            receipt_number=row.receipt_number,
            amount_ugx=float(row.amount),
            period=row.period_label or "",
            property_name=row.property_name or "",
            verify_url=verify_url,
            pdf_path=row.pdf_path,
        )
    else:
        _send_receipt_email(db, row, tenant)
    row.emailed_at = datetime.now(timezone.utc)
    db.commit()


def admin_stats(db: Session) -> dict:
    total = db.query(SystemReceipt).filter(SystemReceipt.is_void == False).count()  # noqa: E712
    paid = db.query(SystemReceipt).filter(SystemReceipt.status == ReceiptStatus.paid).count()
    escrowed = db.query(SystemReceipt).filter(SystemReceipt.status == ReceiptStatus.escrowed).count()
    with_chain = db.query(SystemReceipt).filter(SystemReceipt.tx_hash.isnot(None)).count()
    return {
        "total_receipts": total,
        "paid": paid,
        "escrowed": escrowed,
        "blockchain_verified": with_chain,
    }
