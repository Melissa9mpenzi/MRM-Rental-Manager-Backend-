"""Tenant rent invoices — create and resolve payable bills."""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.invoice import Invoice, InvoiceStatus
from app.models.lease import Lease, LeaseStatus
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)


def generate_invoice_number(db: Session, owner_id: int) -> str:
    prefix = f"INV-{owner_id}-{datetime.now().strftime('%y%m%d')}"
    count = db.query(Invoice).filter(Invoice.invoice_number.like(f"{prefix}-%")).count()
    return f"{prefix}-{count + 1:03d}"


def _norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def resolve_tenant_for_user(db: Session, user) -> Tenant | None:
    """
    Return the tenant row for this login.

    Handles:
    - Already linked by user_id
    - Landlord created tenant first (user_id null, same email)
    - Accepted invite with password but now signs in with Google/Privy (same email, different session)
    """
    tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
    if tenant:
        return tenant

    email = _norm_email(user.email)
    if not email:
        return None

    candidates = (
        db.query(Tenant)
        .filter(Tenant.email.isnot(None))
        .order_by(Tenant.id.desc())
        .all()
    )
    for row in candidates:
        if _norm_email(row.email) != email:
            continue
        if row.user_id == user.id:
            return row
        if row.user_id is None:
            row.user_id = user.id
            if not row.phone and getattr(user, "phone", None):
                row.phone = user.phone
            db.commit()
            db.refresh(row)
            logger.info("Auto-linked tenant id=%s to user id=%s (unlinked)", row.id, user.id)
            return row
        linked = db.query(User).filter(User.id == row.user_id).first()
        if linked and _norm_email(getattr(linked, "email", None)) == email:
            row.user_id = user.id
            if not row.phone and getattr(user, "phone", None):
                row.phone = user.phone
            db.commit()
            db.refresh(row)
            logger.info(
                "Re-linked tenant id=%s from user id=%s to user id=%s (same email)",
                row.id,
                linked.id,
                user.id,
            )
            return row
    return None


def _month_due_date(lease_start: date, year: int, month: int) -> date:
    dom = lease_start.day
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(dom, last))


def ensure_current_rent_invoice(db: Session, tenant: Tenant) -> Invoice | None:
    """
    Ensure the active lease has a payable invoice for the current calendar month.
    Idempotent — safe to call on every tenant pay-page load.
    """
    lease = (
        db.query(Lease)
        .filter(Lease.tenant_id == tenant.id, Lease.status == LeaseStatus.active)
        .first()
    )
    if not lease:
        return None

    today = date.today()
    period_month, period_year = today.month, today.year

    existing = (
        db.query(Invoice)
        .filter(
            Invoice.lease_id == lease.id,
            Invoice.period_month == period_month,
            Invoice.period_year == period_year,
            Invoice.is_deleted == False,
        )
        .first()
    )
    if existing:
        if float(existing.balance_due or 0) > 0 and existing.status not in (
            InvoiceStatus.paid,
            InvoiceStatus.cancelled,
        ):
            if existing.status == InvoiceStatus.draft:
                existing.status = InvoiceStatus.sent
                db.commit()
            return existing
        if existing.status == InvoiceStatus.paid:
            return None
        return existing

    rent = lease.monthly_rent or tenant.monthly_rent
    if rent is None or float(rent) <= 0:
        logger.warning("ensure_current_rent_invoice: no rent amount tenant=%s", tenant.id)
        return None

    rent_dec = Decimal(str(float(rent)))
    due = _month_due_date(lease.start_date or today, period_year, period_month)

    invoice = Invoice(
        lease_id=lease.id,
        tenant_id=tenant.id,
        unit_id=lease.unit_id,
        owner_id=lease.owner_id,
        invoice_number=generate_invoice_number(db, lease.owner_id),
        period_month=period_month,
        period_year=period_year,
        due_date=due,
        rent_amount=rent_dec,
        penalty_amount=Decimal("0"),
        discount_amount=Decimal("0"),
        total_amount=rent_dec,
        amount_paid=Decimal("0"),
        balance_due=rent_dec,
        status=InvoiceStatus.sent,
        description=f"Rent for {period_month:02d}/{period_year}",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    logger.info("Created rent invoice %s for tenant %s", invoice.invoice_number, tenant.id)
    return invoice


def serialize_invoice(inv: Invoice) -> dict:
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "period_month": inv.period_month,
        "period_year": inv.period_year,
        "due_date": str(inv.due_date),
        "rent_amount": float(inv.rent_amount),
        "penalty_amount": float(inv.penalty_amount),
        "discount_amount": float(inv.discount_amount),
        "total_amount": float(inv.total_amount),
        "amount_paid": float(inv.amount_paid),
        "balance_due": float(inv.balance_due),
        "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
        "description": inv.description,
    }
