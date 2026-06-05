from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.models.lease import Lease, LeaseStatus
from app.models.property import Unit
from app.models.tenant import Tenant, TenantStatus
from app.services.blockchain import walrus_anchor_service
from app.services.verification_service import verify_page_url


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
        **walrus_anchor_service.proof_fields(
            getattr(lease, "walrus_blob_id", None),
            content_hash=getattr(lease, "agreement_hash", None),
        ),
        "agreement_hash": getattr(lease, "agreement_hash", None),
        "verification_token": getattr(lease, "verification_token", None),
        "verification_url": verify_page_url(lease.verification_token)
        if getattr(lease, "verification_token", None)
        else None,
    }


def create_lease_for_tenant(
    db: Session,
    tenant: Tenant,
    owner_id: int,
    *,
    anchor: bool = True,
) -> Lease:
    """Ensure an active lease exists for a tenant (contracts list uses leases, not tenants alone)."""
    existing = (
        db.query(Lease)
        .filter(
            Lease.tenant_id == tenant.id,
            Lease.status.in_([LeaseStatus.active, LeaseStatus.pending, LeaseStatus.draft]),
        )
        .first()
    )
    if existing:
        return existing

    if not tenant.unit_id:
        raise ValueError("Tenant has no unit assigned")

    lease = Lease(
        tenant_id=tenant.id,
        unit_id=tenant.unit_id,
        owner_id=owner_id,
        start_date=tenant.lease_start,
        end_date=tenant.lease_end,
        monthly_rent=tenant.monthly_rent,
        deposit_amount=tenant.deposit_amount or 0,
        deposit_paid=bool(tenant.deposit_paid),
        deposit_receipt_path=tenant.deposit_receipt_path,
        status=LeaseStatus.active,
        notes=tenant.notes,
    )
    db.add(lease)
    db.flush()
    if anchor:
        try:
            walrus_anchor_service.anchor_lease_agreement(db, lease)
        except Exception:  # noqa: BLE001
            pass
    return lease


def sync_tenant_leases_for_owner(db: Session, owner_id: int) -> int:
    """Backfill leases for tenants added before auto-contract creation."""
    tenants = (
        db.query(Tenant)
        .filter(Tenant.owner_id == owner_id, Tenant.unit_id.isnot(None))
        .filter(Tenant.status == TenantStatus.active)
        .all()
    )
    created = 0
    for tenant in tenants:
        has_lease = (
            db.query(Lease)
            .filter(
                Lease.tenant_id == tenant.id,
                Lease.status.in_([LeaseStatus.active, LeaseStatus.pending, LeaseStatus.draft]),
            )
            .first()
        )
        if has_lease:
            continue
        create_lease_for_tenant(db, tenant, owner_id, anchor=True)
        created += 1
    if created:
        db.commit()
    return created


def list_leases_for_owner(
    db: Session,
    owner_id: int,
    *,
    tenant_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    sync_tenant_leases_for_owner(db, owner_id)
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
