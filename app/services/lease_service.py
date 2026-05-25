from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.models.lease import Lease
from app.models.property import Unit
from app.models.tenant import Tenant


def _iso(value: date | datetime | None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _money(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def _status_value(status) -> str:
    if status is None:
        return "draft"
    return status.value if hasattr(status, "value") else str(status)


def serialize_lease(lease: Lease) -> dict[str, Any]:
    tenant: Tenant | None = lease.tenant
    unit: Unit | None = lease.unit
    prop = unit.parent_property if unit else None
    return {
        "id": lease.id,
        "tenant_id": lease.tenant_id,
        "unit_id": lease.unit_id,
        "owner_id": lease.owner_id,
        "start_date": _iso(lease.start_date),
        "end_date": _iso(lease.end_date),
        "monthly_rent": _money(lease.monthly_rent),
        "deposit_amount": _money(lease.deposit_amount),
        "deposit_paid": bool(lease.deposit_paid),
        "deposit_receipt_path": lease.deposit_receipt_path,
        "status": _status_value(lease.status),
        "termination_date": _iso(lease.termination_date),
        "termination_reason": lease.termination_reason,
        "notes": lease.notes,
        "created_at": _iso(lease.created_at),
        "updated_at": _iso(lease.updated_at),
        "tenant_name": tenant.full_name if tenant else None,
        "tenant_phone": tenant.phone if tenant else None,
        "unit_number": unit.unit_number if unit else None,
        "property_name": prop.name if prop else None,
        "property_id": prop.id if prop else None,
    }


def list_leases_for_owner(
    db: Session,
    owner_id: int,
    *,
    tenant_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    q = (
        db.query(Lease)
        .options(
            joinedload(Lease.tenant),
            joinedload(Lease.unit).joinedload(Unit.parent_property),
        )
        .filter(Lease.owner_id == owner_id)
    )
    if tenant_id is not None:
        q = q.filter(Lease.tenant_id == tenant_id)
    if unit_id is not None:
        q = q.filter(Lease.unit_id == unit_id)
    if status:
        q = q.filter(Lease.status == status)
    rows = q.order_by(Lease.created_at.desc()).all()
    return [serialize_lease(row) for row in rows]


def get_lease_for_owner(db: Session, lease_id: int, owner_id: int) -> Optional[dict[str, Any]]:
    lease = (
        db.query(Lease)
        .options(
            joinedload(Lease.tenant),
            joinedload(Lease.unit).joinedload(Unit.parent_property),
        )
        .filter(Lease.id == lease_id, Lease.owner_id == owner_id)
        .first()
    )
    if not lease:
        return None
    return serialize_lease(lease)
