import enum
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

logger = logging.getLogger(__name__)

from app.models.payment import Payment, PaymentMethod, PaymentType
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.property import Unit
from app.models.user import User, UserRole
from app.schemas.payment import PaymentCreate, PaymentUpdate


MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

_ONLINE_METHODS = {
    PaymentMethod.mtn_momo.value,
    PaymentMethod.airtel.value,
    PaymentMethod.sui.value,
    PaymentMethod.pesapal.value,
    PaymentMethod.card.value,
    PaymentMethod.other.value,
}


def parse_payment_method(raw: str) -> PaymentMethod:
    """Normalize and validate payment method (cash not allowed)."""
    key = (raw or PaymentMethod.mtn_momo.value).strip().lower()
    if key == "cash":
        raise HTTPException(
            400,
            "Cash is not supported. Use MTN MoMo, Airtel, bank transfer, Pesapal, or Sui.",
        )
    aliases = {
        "mtn": PaymentMethod.mtn_momo,
        "momo": PaymentMethod.mtn_momo,
        "mobile_money": PaymentMethod.mtn_momo,
        "momo_mtn": PaymentMethod.mtn_momo,
        "momo_airtel": PaymentMethod.airtel,
        "bank_transfer": PaymentMethod.bank,
        "visa": PaymentMethod.card,
        "mastercard": PaymentMethod.card,
    }
    if key in aliases:
        return aliases[key]
    try:
        method = PaymentMethod(key)
    except ValueError:
        raise HTTPException(
            400,
            f"Unsupported payment method: {raw}. Use mtn_momo, airtel, bank, pesapal, card, or sui.",
        )
    if method == PaymentMethod.cash:
        raise HTTPException(
            400,
            "Cash is not supported. Use MTN MoMo, Airtel, bank transfer, Pesapal, or Sui.",
        )
    return method


def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_safe_value(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _enrich(p: Payment) -> dict:
    tenant = p.tenant
    unit   = tenant.unit if tenant else None
    prop   = unit.parent_property if unit else None
    raw = {
        k: _json_safe_value(v)
        for k, v in p.__dict__.items()
        if not k.startswith("_")
    }
    raw["tenant_name"] = tenant.full_name if tenant else None
    raw["unit_number"] = unit.unit_number if unit else None
    raw["property_name"] = prop.name if prop else None
    return raw


def _load(db: Session, payment_id: int, owner_id: int) -> Payment:
    p = (
        db.query(Payment)
        .options(joinedload(Payment.tenant).joinedload(Tenant.unit).joinedload(Unit.parent_property))
        .filter(Payment.id == payment_id, Payment.owner_id == owner_id, Payment.is_deleted == False)
        .first()
    )
    if not p:
        raise HTTPException(404, "Payment not found")
    return p


def get_tenant_payments(db: Session, tenant_id: int, owner_id: int) -> list:
    t = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.owner_id == owner_id).first()
    if not t:
        raise HTTPException(404, "Tenant not found")
    rows = (
        db.query(Payment)
        .options(joinedload(Payment.tenant).joinedload(Tenant.unit).joinedload(Unit.parent_property))
        .filter(Payment.tenant_id == tenant_id, Payment.owner_id == owner_id, Payment.is_deleted == False)
        .order_by(Payment.payment_date.desc())
        .all()
    )
    return [_enrich(p) for p in rows]


def get_all_payments(db: Session, owner_id: int, limit: int = 100, offset: int = 0) -> list:
    rows = (
        db.query(Payment)
        .options(joinedload(Payment.tenant).joinedload(Tenant.unit).joinedload(Unit.parent_property))
        .filter(Payment.owner_id == owner_id, Payment.is_deleted == False)
        .order_by(Payment.payment_date.desc())
        .limit(limit).offset(offset)
        .all()
    )
    return [_enrich(p) for p in rows]


def settle_invoice_payment(
    db: Session,
    invoice: Invoice,
    *,
    amount: Decimal,
    payment_method: str,
    reference: str | None,
    payment_date: date | None = None,
    notes: str | None = None,
) -> Payment:
    """Create a rent payment and update invoice balances (used by gateway webhooks)."""
    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.cancelled):
        raise HTTPException(409, f"Invoice is already {invoice.status.value}")

    if amount > invoice.balance_due:
        raise HTTPException(400, f"Payment amount exceeds balance due ({invoice.balance_due})")

    method_enum = parse_payment_method(payment_method)
    gross = Decimal(str(amount))
    from app.services import platform_fee_service

    fee = (
        platform_fee_service.calculate_online_rent_fee(gross)
        if platform_fee_service.is_online_payment_method(method_enum)
        else Decimal("0")
    )
    net = gross - fee

    payment = Payment(
        tenant_id=invoice.tenant_id,
        lease_id=invoice.lease_id,
        unit_id=invoice.unit_id,
        owner_id=invoice.owner_id,
        amount=gross,
        gross_amount=gross,
        platform_fee=fee,
        net_to_landlord=net,
        payment_type=PaymentType.rent,
        payment_method=method_enum,
        reference=reference,
        period_month=invoice.period_month,
        period_year=invoice.period_year,
        payment_date=payment_date or date.today(),
        notes=notes or "Gateway settlement",
    )

    invoice.amount_paid = Decimal(str(invoice.amount_paid)) + amount
    invoice.balance_due = invoice.total_amount - invoice.amount_paid

    if invoice.balance_due <= 0:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = datetime.now(timezone.utc)
    else:
        invoice.status = InvoiceStatus.partial

    db.add(payment)
    db.flush()

    try:
        platform_fee_service.record_online_rent_settlement(
            db,
            owner_id=invoice.owner_id,
            payment_id=payment.id,
            gross_ugx=gross,
            payment_method=method_enum.value,
            reference=reference,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("landlord ledger settlement skipped: %s", exc)

    try:
        from app.models.notification import Notification, NotifType

        tenant = db.query(Tenant).filter(Tenant.id == invoice.tenant_id).first()
        fee_note = f" (platform fee UGX {float(fee):,.0f}, net UGX {float(net):,.0f})" if fee > 0 else ""
        note = Notification(
            user_id=invoice.owner_id,
            title="Payment received",
            message=(
                f"{tenant.full_name if tenant else 'Tenant'} paid UGX {float(gross):,.0f} "
                f"for {MONTHS[invoice.period_month - 1]} {invoice.period_year} (online).{fee_note}"
            ),
            notif_type=NotifType.payment_received,
            link=f"/landlord/tenants/{invoice.tenant_id}",
        )
        db.add(note)
    except Exception:
        pass

    return payment


def record_payment(db: Session, data: PaymentCreate, owner_id: int) -> dict:
    # Verify tenant belongs to owner
    tenant = db.query(Tenant).filter(Tenant.id == data.tenant_id, Tenant.owner_id == owner_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    payload = data.model_dump()
    payload["payment_method"] = parse_payment_method(payload.get("payment_method") or "mtn_momo")
    payment = Payment(
        owner_id=owner_id,
        unit_id=tenant.unit_id,
        **payload,
    )
    db.add(payment)
    db.commit()
    db.expire(payment)

    try:
        from app.runtime import upload_root
        from app.services import receipt_service

        p_loaded = _load(db, payment.id, owner_id)
        receipt_service.issue_from_payment(db, p_loaded, upload_dir=upload_root())
        db.commit()
    except Exception:
        db.rollback()

    # Notification
    try:
        from app.models.notification import Notification, NotifType
        note = Notification(
            user_id=owner_id,
            title="Payment received",
            message=f"{tenant.full_name} paid UGX {float(data.amount):,.0f} for {MONTHS[data.period_month-1]} {data.period_year}.",
            notif_type=NotifType.payment_received,
            link=f"/landlord/tenants/{tenant.id}",
        )
        db.add(note)
        db.commit()
    except Exception:
        pass

    return _enrich(_load(db, payment.id, owner_id))


def update_payment(db: Session, payment_id: int, data: PaymentUpdate, owner_id: int) -> dict:
    p = _load(db, payment_id, owner_id)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return _enrich(_load(db, payment_id, owner_id))


def delete_payment(db: Session, payment_id: int, owner_id: int):
    p = _load(db, payment_id, owner_id)
    p.is_deleted = True
    db.commit()


def _role_value(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def wallet_summary_for_user(db: Session, user: User) -> dict:
    """Aggregate rent payments visible to this user (tenant: own payments; landlord: collected; admin: platform-wide)."""
    from app.models.property import Property, Unit, UnitStatus
    from app.models.escrow_hold import EscrowHold, EscrowStatus
    from app.services.arrears_service import get_arrears_list

    today = date.today()
    q = (
        db.query(Payment)
        .filter(Payment.is_deleted == False, Payment.payment_type == PaymentType.rent)
        .options(joinedload(Payment.tenant).joinedload(Tenant.unit).joinedload(Unit.parent_property))
    )

    role = _role_value(user)
    if role == UserRole.tenant.value:
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        if not tenant:
            return {
                "total_paid_ugx": 0.0,
                "payment_count": 0,
                "by_method": {},
                "scope": "tenant",
            }
        q = q.filter(Payment.tenant_id == tenant.id)
        scope = "tenant"
    elif role == UserRole.system_admin.value:
        scope = "platform"
    else:
        q = q.filter(Payment.owner_id == user.id)
        scope = "landlord"

    rows = q.order_by(Payment.payment_date.desc(), Payment.id.desc()).all()
    total = sum(float(p.amount) for p in rows)
    by_method: dict[str, float] = {}
    by_method_online = 0.0
    by_method_manual = 0.0
    manual_keys = {PaymentMethod.bank.value}
    for p in rows:
        pm = p.payment_method
        try:
            key = pm.value if hasattr(pm, "value") else str(pm or "other")
        except Exception:  # noqa: BLE001
            key = "other"
        amt = _safe_float(p.amount)
        by_method[key] = by_method.get(key, 0.0) + amt
        if key in manual_keys:
            by_method_manual += amt
        else:
            by_method_online += amt

    this_month = sum(
        float(p.amount)
        for p in rows
        if p.period_month == today.month and p.period_year == today.year
    )

    payload: dict = {
        "total_paid_ugx": round(total, 2),
        "total_collected_ugx": round(total, 2),
        "this_month_collected_ugx": round(this_month, 2),
        "payment_count": len(rows),
        "by_method": by_method,
        "by_method_online_ugx": round(by_method_online, 2),
        "by_method_manual_ugx": round(by_method_manual, 2),
        "scope": scope,
        "recent_payments": [_enrich(p) for p in rows[:12]],
    }

    if scope == "landlord":
        arrears = get_arrears_list(db, user.id)
        outstanding = sum(
            _safe_float(a.get("balance_due"))
            for a in arrears
            if _safe_float(a.get("balance_due")) > 0
        )
        properties = (
            db.query(Property)
            .options(joinedload(Property.units))
            .filter(Property.owner_id == user.id, Property.is_active == True)
            .all()
        )
        all_units = [u for p in properties for u in p.units]
        occupied = UnitStatus.occupied.value
        expected_monthly = sum(
            _safe_float(u.rent_amount)
            for u in all_units
            if (u.status.value if hasattr(u.status, "value") else str(u.status)) == occupied
        )
        active_escrow = []
        try:
            from sqlalchemy import inspect as sa_inspect

            from app.database import engine, postgres_table_schema

            schema = postgres_table_schema if postgres_table_schema else None
            if sa_inspect(engine).has_table("escrow_holds", schema=schema):
                active_escrow = (
                    db.query(EscrowHold)
                    .filter(
                        EscrowHold.owner_id == user.id,
                        EscrowHold.status.in_(
                            [EscrowStatus.pending, EscrowStatus.funded, EscrowStatus.held]
                        ),
                    )
                    .all()
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("wallet_summary escrow query skipped: %s", exc)
        escrow_held = sum(_safe_float(h.amount_ugx) for h in active_escrow)
        try:
            from app.services import platform_fee_service

            balance = platform_fee_service.landlord_balance_summary(db, user.id)
            payload["landlord_balance"] = {
                "available_balance_ugx": balance["available_balance_ugx"],
                "lifetime_platform_fees_ugx": balance["lifetime_platform_fees_ugx"],
                "estimated_monthly_unit_fees_ugx": balance["estimated_monthly_unit_fees_ugx"],
                "active_units": balance["active_units"],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("wallet_summary landlord_balance skipped: %s", exc)

        payload.update(
            {
                "available_ugx": round(total, 2),
                "outstanding_rent_ugx": round(outstanding, 2),
                "expected_monthly_rent_ugx": round(expected_monthly, 2),
                "tenants_in_arrears": sum(
                    1 for a in arrears if _safe_float(a.get("balance_due")) > 0
                ),
                "escrow_held_ugx": round(escrow_held, 2),
                "escrow_active_count": len(active_escrow),
                "collection_rate_pct": round(this_month / expected_monthly * 100, 1)
                if expected_monthly > 0
                else 0.0,
            }
        )

    return payload


# ── PDF RECEIPT ────────────────────────────────────────────────────────────────

def generate_receipt_pdf(db: Session, payment_id: int, owner_id: int, upload_dir: str) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm

    p = _load(db, payment_id, owner_id)
    tenant = p.tenant
    unit   = tenant.unit if tenant else None
    prop   = unit.parent_property if unit else None

    # File path
    receipts_dir = os.path.join(upload_dir, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)
    filename = f"receipt_{p.id:05d}.pdf"
    filepath = os.path.join(receipts_dir, filename)

    doc    = SimpleDocTemplate(filepath, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    teal   = colors.HexColor("#5e8d83")
    dark   = colors.HexColor("#161d23")

    title_style = ParagraphStyle("title", parent=styles["Heading1"], textColor=teal, fontSize=20, spaceAfter=4)
    sub_style   = ParagraphStyle("sub",   parent=styles["Normal"],   textColor=dark, fontSize=9,  spaceAfter=2)

    story = [
        Paragraph("RentalMGR", title_style),
        Paragraph("Official Payment Receipt", sub_style),
        Spacer(1, 0.4*cm),
    ]

    info_data = [
        ["Receipt #",  f"REC-{p.id:05d}"],
        ["Date",       p.payment_date.strftime("%d %B %Y")],
        ["Period",     f"{MONTHS[p.period_month-1]} {p.period_year}"],
        ["Method",     p.payment_method.replace("_"," ").title()],
        ["Reference",  p.reference or "—"],
    ]
    info_table = Table(info_data, colWidths=[4*cm, 10*cm])
    info_table.setStyle(TableStyle([
        ("FONTSIZE",    (0,0), (-1,-1), 9),
        ("TEXTCOLOR",  (0,0), (0,-1), colors.grey),
        ("TEXTCOLOR",  (1,0), (1,-1), dark),
        ("FONTNAME",   (0,0), (0,-1), "Helvetica"),
        ("FONTNAME",   (1,0), (1,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.whitesmoke, colors.white]),
        ("TOPPADDING",  (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.5*cm))

    tenant_data = [
        ["Tenant",    tenant.full_name if tenant else "—"],
        ["Phone",     tenant.phone if tenant else "—"],
        ["Unit",      unit.unit_number if unit else "—"],
        ["Property",  prop.name if prop else "—"],
        ["Address",   prop.address if prop else "—"],
    ]
    tenant_table = Table(tenant_data, colWidths=[4*cm, 10*cm])
    tenant_table.setStyle(TableStyle([
        ("FONTSIZE",    (0,0), (-1,-1), 9),
        ("TEXTCOLOR",  (0,0), (0,-1), colors.grey),
        ("TEXTCOLOR",  (1,0), (1,-1), dark),
        ("FONTNAME",   (0,0), (0,-1), "Helvetica"),
        ("FONTNAME",   (1,0), (1,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.whitesmoke, colors.white]),
        ("TOPPADDING",  (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(tenant_table)
    story.append(Spacer(1, 0.6*cm))

    # Amount block
    amount_data = [
        ["AMOUNT PAID", f"UGX {float(p.amount):,.0f}"],
        ["Payment type", p.payment_type.replace("_"," ").title()],
    ]
    amount_table = Table(amount_data, colWidths=[4*cm, 10*cm])
    amount_table.setStyle(TableStyle([
        ("FONTSIZE",    (0,0), (0,0), 9),
        ("FONTSIZE",    (1,0), (1,0), 16),
        ("TEXTCOLOR",  (0,0), (-1,-1), colors.white),
        ("BACKGROUND", (0,0), (-1,-1), teal),
        ("FONTNAME",   (0,0), (-1,-1), "Helvetica-Bold"),
        ("TOPPADDING",  (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [teal, colors.HexColor("#4a7a70")]),
    ]))
    story.append(amount_table)

    if p.notes:
        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph(f"Notes: {p.notes}", sub_style))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Thank you for your payment.", ParagraphStyle("footer", parent=styles["Normal"], textColor=colors.grey, fontSize=8)))
    story.append(Paragraph("This is a computer-generated receipt.", ParagraphStyle("footer2", parent=styles["Normal"], textColor=colors.grey, fontSize=8)))

    doc.build(story)
    return f"/uploads/receipts/{filename}"