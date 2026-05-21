from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import date
from decimal import Decimal

from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models.user import User
from app.models.tenant import Tenant
from app.models.lease import Lease, LeaseStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentType, PaymentMethod
from app.schemas.invoice import InvoiceCreate, InvoiceOut, InvoicePayment
from datetime import datetime
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/invoices", tags=["Invoices"])


def generate_invoice_number(db: Session, owner_id: int) -> str:
    """Generate unique invoice number: INV-{owner_id}-{YYMMDD}-{seq}"""
    from datetime import datetime
    prefix = f"INV-{owner_id}-{datetime.now().strftime('%y%m%d')}"
    count = db.query(Invoice).filter(Invoice.invoice_number.like(f"{prefix}-%")).count()
    return f"{prefix}-{count + 1:03d}"


@router.post("/", status_code=201)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["system_admin", "staff", "landlord"])),
):
    """Create invoice with standardized response"""
    # Verify lease exists and belongs to user
    lease = db.query(Lease).filter(
        Lease.id == payload.lease_id,
        Lease.owner_id == current_user.id,
        Lease.status == LeaseStatus.active,
    ).first()
    if not lease:
        raise error_response("Active lease not found or access denied.", status_code=404)

    # Check for duplicate invoice for same period
    existing = db.query(Invoice).filter(
        Invoice.lease_id == payload.lease_id,
        Invoice.period_month == payload.period_month,
        Invoice.period_year == payload.period_year,
        Invoice.is_deleted == False,
    ).first()
    if existing:
        raise error_response(f"Invoice already exists for {payload.period_month}/{payload.period_year}.", status_code=409)

    total = payload.rent_amount + (payload.penalty_amount or 0) - (payload.discount_amount or 0)

    invoice = Invoice(
        lease_id=payload.lease_id,
        tenant_id=lease.tenant_id,
        unit_id=lease.unit_id,
        owner_id=current_user.id,
        invoice_number=generate_invoice_number(db, current_user.id),
        period_month=payload.period_month,
        period_year=payload.period_year,
        due_date=payload.due_date,
        rent_amount=payload.rent_amount,
        penalty_amount=payload.penalty_amount or 0,
        discount_amount=payload.discount_amount or 0,
        total_amount=total,
        amount_paid=0,
        balance_due=total,
        status=InvoiceStatus.draft,
        description=payload.description,
        notes=payload.notes,
    )

    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return success_response(data=invoice, message="Invoice created successfully")


@router.get("/")
def list_invoices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    lease_id: int = None,
    status: str = None,
    tenant_id: int = None,
):
    """List invoices. Admin/Staff see all. Tenants see only their own."""
    q = db.query(Invoice).filter(Invoice.is_deleted == False)

    if current_user.role == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        if not tenant:
            return success_response(data=[])
        q = q.filter(Invoice.tenant_id == tenant.id)
    elif current_user.role in ("landlord", "staff"):
        q = q.filter(Invoice.owner_id == current_user.id)

    if lease_id:
        q = q.filter(Invoice.lease_id == lease_id)
    if tenant_id:
        q = q.filter(Invoice.tenant_id == tenant_id)
    if status:
        q = q.filter(Invoice.status == status)

    invoices = q.order_by(Invoice.created_at.desc()).all()
    return success_response(data=invoices)


@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single invoice with standardized response"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.is_deleted == False).first()
    if not invoice:
        raise error_response("Invoice not found.", status_code=404)

    if current_user.role == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        if not tenant or invoice.tenant_id != tenant.id:
            raise error_response("Access denied.", status_code=403)
    elif current_user.role in ("landlord", "staff") and invoice.owner_id != current_user.id:
        raise error_response("Access denied.", status_code=403)

    return success_response(data=invoice)


@router.post("/{invoice_id}/payments")
def record_payment(
    invoice_id: int,
    payload: InvoicePayment,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["system_admin", "staff", "landlord"])),
):
    """Record a payment against an invoice with standardized response"""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.owner_id == current_user.id,
        Invoice.is_deleted == False,
    ).first()
    if not invoice:
        raise error_response("Invoice not found or access denied.", status_code=404)

    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.cancelled):
        raise error_response(f"Invoice is already {invoice.status.value}.", status_code=409)

    # Validate amount
    if payload.amount > invoice.balance_due:
        raise error_response(f"Payment amount exceeds balance due ({invoice.balance_due}).", status_code=400)

    # Create payment record
    lease = db.query(Lease).filter(Lease.id == invoice.lease_id).first()
    payment = Payment(
        tenant_id=invoice.tenant_id,
        lease_id=invoice.lease_id,
        unit_id=invoice.unit_id,
        owner_id=current_user.id,
        amount=payload.amount,
        payment_type=PaymentType.rent,
        payment_method=PaymentMethod(payload.payment_method),
        reference=payload.reference,
        period_month=invoice.period_month,
        period_year=invoice.period_year,
        payment_date=payload.payment_date,
        notes=payload.notes,
    )

    # Update invoice
    invoice.amount_paid = Decimal(str(invoice.amount_paid)) + payload.amount
    invoice.balance_due = invoice.total_amount - invoice.amount_paid

    if invoice.balance_due <= 0:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = datetime.now()
    else:
        invoice.status = InvoiceStatus.partial

    db.add(payment)
    db.commit()
    db.refresh(invoice)
    return success_response(data=invoice, message="Payment recorded successfully")


@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["system_admin", "staff", "landlord"])),
):
    """Soft-delete an invoice (only if not paid) with standardized response"""
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.owner_id == current_user.id,
    ).first()
    if not invoice:
        raise error_response("Invoice not found or access denied.", status_code=404)

    if invoice.status == InvoiceStatus.paid:
        raise error_response("Cannot delete a paid invoice.", status_code=409)

    invoice.is_deleted = True
    invoice.status = InvoiceStatus.cancelled
    db.commit()
    return success_response(message="Invoice deleted successfully")
