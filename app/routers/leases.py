from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models.user import User
from app.models.lease import Lease, LeaseStatus
from app.models.tenant import Tenant
from app.models.property import Unit, UnitStatus
from app.schemas.lease import LeaseCreate, LeaseUpdate, LeaseTerminate, LeaseOut
from app.services.lease_service import get_lease_for_owner, list_leases_for_owner, serialize_lease
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/leases", tags=["Leases"])


def get_unit_lease_status(db: Session, unit_id: int):
    """Check if unit has an active lease."""
    return db.query(Lease).filter(
        Lease.unit_id == unit_id,
        Lease.status == LeaseStatus.active
    ).first()


@router.post("/", status_code=201)
def create_lease(
    payload: LeaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["system_admin", "staff", "landlord"])),
):
    """Create lease with standardized response"""
    # Verify tenant exists and belongs to user
    tenant = db.query(Tenant).filter(
        Tenant.id == payload.tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    if not tenant:
        raise error_response("Tenant not found or access denied.", status_code=404)

    # Verify unit exists and belongs to user
    unit = db.query(Unit).filter(
        Unit.id == payload.unit_id,
        Unit.parent_property.has(owner_id=current_user.id)
    ).first()
    if not unit:
        raise error_response("Unit not found or access denied.", status_code=404)

    # Check unit is not already occupied by active lease
    existing = get_unit_lease_status(db, payload.unit_id)
    if existing:
        raise error_response("Unit already has an active lease.", status_code=409)

    lease = Lease(
        tenant_id=payload.tenant_id,
        unit_id=payload.unit_id,
        owner_id=current_user.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        monthly_rent=payload.monthly_rent,
        deposit_amount=payload.deposit_amount or 0,
        status=LeaseStatus.active,
        notes=payload.notes,
    )

    unit.status = UnitStatus.occupied
    db.add(lease)
    db.commit()
    db.refresh(lease)
    lease = (
        db.query(Lease)
        .options(
            joinedload(Lease.tenant),
            joinedload(Lease.unit).joinedload(Unit.parent_property),
        )
        .filter(Lease.id == lease.id)
        .first()
    )
    agreement_proof = {}
    try:
        from app.services.blockchain import walrus_anchor_service

        if lease:
            agreement_proof = walrus_anchor_service.anchor_lease_agreement(db, lease)
    except Exception:  # noqa: BLE001
        pass
    return success_response(
        data={
            "id": lease.id,
            "status": lease.status.value,
            "agreement_hash": agreement_proof.get("agreement_hash"),
            "walrus_blob_id": agreement_proof.get("walrus_blob_id"),
        },
        message="Lease created — rental agreement anchored on Walrus.",
    )


@router.get("/")
def list_leases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: int = None,
    unit_id: int = None,
    status: str = None,
):
    """List leases. Admin/Staff see all for their properties. Tenants see only their own."""
    q = db.query(Lease)

    if current_user.role == "tenant":
        # Tenant sees only leases linked through their tenant profile
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        if not tenant:
            return success_response(data=[])
        q = q.filter(Lease.tenant_id == tenant.id)
    elif current_user.role in ("landlord", "staff"):
        data = list_leases_for_owner(
            db,
            current_user.id,
            tenant_id=tenant_id,
            unit_id=unit_id,
            status=status,
        )
        return success_response(data=data)
    # Admin sees all (serialized)

    if tenant_id:
        q = q.filter(Lease.tenant_id == tenant_id)
    if unit_id:
        q = q.filter(Lease.unit_id == unit_id)
    if status:
        q = q.filter(Lease.status == status)

    from sqlalchemy.orm import joinedload
    from app.models.property import Unit

    leases = (
        q.options(joinedload(Lease.tenant), joinedload(Lease.unit).joinedload(Unit.parent_property))
        .order_by(Lease.created_at.desc())
        .all()
    )
    return success_response(data=[serialize_lease(row) for row in leases])


@router.get("/{lease_id}")
def get_lease(
    lease_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single lease with standardized response"""
    from sqlalchemy.orm import joinedload
    from app.models.property import Unit

    lease = (
        db.query(Lease)
        .options(joinedload(Lease.tenant), joinedload(Lease.unit).joinedload(Unit.parent_property))
        .filter(Lease.id == lease_id)
        .first()
    )
    if not lease:
        raise error_response("Lease not found.", status_code=404)

    if current_user.role == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        if not tenant or lease.tenant_id != tenant.id:
            raise error_response("Access denied.", status_code=403)
    elif current_user.role in ("landlord", "staff") and lease.owner_id != current_user.id:
        raise error_response("Access denied.", status_code=403)

    return success_response(data=serialize_lease(lease))


@router.put("/{lease_id}")
def update_lease(
    lease_id: int,
    payload: LeaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["system_admin", "staff", "landlord"])),
):
    """Update lease with standardized response"""
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    if not lease:
        raise error_response("Lease not found or access denied.", status_code=404)

    if lease.status != LeaseStatus.active:
        raise error_response("Can only update active leases.", status_code=409)

    if payload.end_date is not None:
        lease.end_date = payload.end_date
    if payload.monthly_rent is not None:
        lease.monthly_rent = payload.monthly_rent
    if payload.deposit_amount is not None:
        lease.deposit_amount = payload.deposit_amount
    if payload.notes is not None:
        lease.notes = payload.notes

    db.commit()
    db.refresh(lease)
    row = get_lease_for_owner(db, lease_id, current_user.id)
    return success_response(data=row, message="Lease updated successfully")


@router.post("/{lease_id}/terminate")
def terminate_lease(
    lease_id: int,
    payload: LeaseTerminate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["system_admin", "staff", "landlord"])),
):
    """Terminate lease with standardized response"""
    lease = db.query(Lease).filter(
        Lease.id == lease_id,
        Lease.owner_id == current_user.id
    ).first()
    if not lease:
        raise error_response("Lease not found or access denied.", status_code=404)

    if lease.status != LeaseStatus.active:
        raise error_response("Lease is not active.", status_code=409)

    lease.status = LeaseStatus.terminated
    lease.termination_date = payload.termination_date
    lease.termination_reason = payload.termination_reason

    # Free up the unit
    if lease.unit:
        lease.unit.status = UnitStatus.vacant

    db.commit()
    db.refresh(lease)
    row = get_lease_for_owner(db, lease_id, current_user.id)
    return success_response(data=row, message="Lease terminated successfully")
