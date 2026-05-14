"""
Arrears service — calculates how much a tenant owes.

Logic:
  months_due = number of full months from lease_start to today (inclusive)
  total_due  = months_due * monthly_rent
  total_paid = sum of rent payments (non-deleted)
  balance    = total_due - total_paid  (positive = tenant owes money)
"""
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.tenant import Tenant, TenantStatus
from app.models.payment import Payment, PaymentType


def months_between(start: date, end: date) -> int:
    """Number of rent months that have elapsed from start to end (inclusive)."""
    if end < start:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def compute_tenant_balance(tenant: Tenant, as_of: date = None) -> dict:
    as_of = as_of or date.today()

    if tenant.status != TenantStatus.active:
        return {"months_due": 0, "total_due": Decimal("0"), "total_paid": Decimal("0"), "balance_due": Decimal("0"), "months_in_arrears": 0}

    if tenant.monthly_rent is None:
        return {"months_due": 0, "total_due": Decimal("0"), "total_paid": Decimal("0"), "balance_due": Decimal("0"), "months_in_arrears": 0}

    effective_end = min(tenant.lease_end, as_of) if tenant.lease_end else as_of
    months_due = months_between(tenant.lease_start, effective_end)
    total_due  = Decimal(str(float(tenant.monthly_rent))) * months_due

    total_paid = sum(
        Decimal(str(float(p.amount)))
        for p in tenant.payments
        if not p.is_deleted and p.payment_type == PaymentType.rent
    )

    balance = total_due - total_paid
    monthly = Decimal(str(float(tenant.monthly_rent))) or Decimal("1")
    months_in_arrears = max(0, int(balance / monthly)) if monthly else 0

    return {
        "months_due":       months_due,
        "total_due":        total_due,
        "total_paid":       total_paid,
        "balance_due":      balance,
        "months_in_arrears": months_in_arrears,
    }


def get_arrears_list(db: Session, owner_id: int) -> list:
    """Return all active tenants with their arrears data."""
    from app.models.property import Unit, Property
    from sqlalchemy.orm import joinedload

    tenants = (
        db.query(Tenant)
        .options(joinedload(Tenant.payments), joinedload(Tenant.unit).joinedload(Unit.parent_property))
        .filter(Tenant.owner_id == owner_id, Tenant.status == TenantStatus.active)
        .all()
    )

    result = []
    for t in tenants:
        bal = compute_tenant_balance(t)
        result.append({
            "id":               t.id,
            "full_name":        t.full_name,
            "phone":            t.phone,
            "unit_number":      t.unit.unit_number if t.unit else None,
            "property_name":    t.unit.parent_property.name if t.unit and t.unit.parent_property else None,
            "property_id":      t.unit.parent_property.id if t.unit and t.unit.parent_property else None,
            "monthly_rent":     float(t.monthly_rent),
            **{k: float(v) if isinstance(v, Decimal) else v for k, v in bal.items()},
        })

    return sorted(result, key=lambda x: x["balance_due"], reverse=True)