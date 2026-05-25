from typing import Optional

from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

from app.models.tenant import Tenant, TenantStatus
from app.models.property import Unit, Property, UnitStatus
from app.models.payment import PaymentMethod, PaymentType
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.services.arrears_service import compute_tenant_balance


def _status_value(status) -> str:
    if status is None:
        return "active"
    return status.value if hasattr(status, "value") else str(status)


def _money(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def _iso(value: date | datetime | None):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _payment_splits(tenant: Tenant) -> tuple[float, float]:
    """Rent collected via gateway/MoMo vs manual (cash/bank) — for landlord roster, not payment ledger."""
    online = 0.0
    manual = 0.0
    for p in tenant.payments or []:
        if p.is_deleted or p.payment_type != PaymentType.rent:
            continue
        amt = float(p.amount or 0)
        pm = p.payment_method.value if hasattr(p.payment_method, "value") else str(p.payment_method)
        if pm in (PaymentMethod.cash.value, PaymentMethod.bank.value, "other"):
            manual += amt
        else:
            online += amt
    return online, manual


def _landlord_tenant_scope(owner_id: int):
    """Tenant belongs to landlord via owner_id or occupied unit on their property."""
    return or_(Tenant.owner_id == owner_id, Property.owner_id == owner_id)


def _serialize_tenant(tenant: Tenant) -> dict:
    bal = compute_tenant_balance(tenant)
    paid_online, paid_manual = _payment_splits(tenant)
    unit = tenant.unit
    prop = unit.parent_property if unit else None
    dep = tenant.deposit_amount
    balance_due = _money(bal["balance_due"])
    return {
        "id": tenant.id,
        "owner_id": tenant.owner_id,
        "user_id": tenant.user_id,
        "unit_id": tenant.unit_id,
        "full_name": tenant.full_name,
        "phone": tenant.phone,
        "email": tenant.email,
        "national_id": tenant.national_id,
        "emergency_contact_name": tenant.emergency_contact_name,
        "emergency_contact_phone": tenant.emergency_contact_phone,
        "lease_start": _iso(tenant.lease_start),
        "lease_end": _iso(tenant.lease_end),
        "monthly_rent": _money(tenant.monthly_rent),
        "deposit_amount": _money(dep if dep is not None else Decimal("0")),
        "deposit_paid": bool(tenant.deposit_paid) if tenant.deposit_paid is not None else False,
        "deposit_receipt_path": tenant.deposit_receipt_path,
        "status": _status_value(tenant.status),
        "notes": tenant.notes,
        "created_at": _iso(tenant.created_at),
        "updated_at": _iso(tenant.updated_at),
        "unit_number": unit.unit_number if unit else None,
        "property_name": prop.name if prop else None,
        "property_id": prop.id if prop else None,
        "balance_due": balance_due,
        "months_in_arrears": bal["months_in_arrears"],
        "total_paid": _money(bal["total_paid"]),
        "total_owed": _money(bal["total_due"]),
        "total_paid_online": paid_online,
        "total_paid_manual": paid_manual,
        "balance": balance_due,
        "months_behind": bal["months_in_arrears"],
    }


class TenantService:
    def _base_query(self, db: Session, owner_id: int):
        return (
            db.query(Tenant)
            .outerjoin(Unit, Tenant.unit_id == Unit.id)
            .outerjoin(Property, Unit.property_id == Property.id)
            .options(
                joinedload(Tenant.payments),
                joinedload(Tenant.unit).joinedload(Unit.parent_property),
            )
            .filter(_landlord_tenant_scope(owner_id))
        )

    def _load(self, db: Session, tenant_id: int, owner_id: int) -> Tenant:
        t = self._base_query(db, owner_id).filter(Tenant.id == tenant_id).first()
        if not t:
            raise HTTPException(404, "Tenant not found")
        return t

    def list_tenants(
        self,
        db: Session,
        owner_id: int,
        search: Optional[str] = None,
        status: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> list:
        return self.get_all_tenants(
            db,
            owner_id,
            search=search or "",
            status_filter=status or "",
            unit_id=unit_id,
        )

    def get_all_tenants(
        self,
        db: Session,
        owner_id: int,
        search: str = "",
        status_filter: str = "",
        unit_id: Optional[int] = None,
    ) -> list:
        q = self._base_query(db, owner_id)
        if search:
            like = f"%{search}%"
            q = q.filter(
                (Tenant.full_name.ilike(like))
                | (Tenant.phone.ilike(like))
                | (Tenant.email.ilike(like))
            )
        if status_filter:
            try:
                st = TenantStatus(status_filter)
                q = q.filter(Tenant.status == st)
            except ValueError:
                pass
        if unit_id is not None:
            q = q.filter(Tenant.unit_id == unit_id)

        rows = q.order_by(Tenant.created_at.desc()).all()
        seen: set[int] = set()
        out: list = []
        for t in rows:
            if t.id in seen:
                continue
            seen.add(t.id)
            out.append(_serialize_tenant(t))
        return out

    def get_tenant(self, db: Session, tenant_id: int, owner_id: int) -> dict:
        return _serialize_tenant(self._load(db, tenant_id, owner_id))

    def create_tenant(self, db: Session, data: TenantCreate, owner_id: int) -> dict:
        if not data.unit_id:
            raise HTTPException(400, "unit_id is required")

        unit = (
            db.query(Unit)
            .join(Property)
            .filter(
                Unit.id == data.unit_id,
                Property.owner_id == owner_id,
            )
            .first()
        )

        if not unit:
            raise HTTPException(404, "Unit not found")
        if unit.status == UnitStatus.occupied:
            raise HTTPException(400, "Unit is already occupied")

        try:
            st = TenantStatus(data.status) if isinstance(data.status, str) else TenantStatus.active
        except ValueError:
            st = TenantStatus.active

        dep = data.deposit_amount if data.deposit_amount is not None else Decimal("0")

        tenant = Tenant(
            owner_id=owner_id,
            unit_id=data.unit_id,
            full_name=data.full_name,
            phone=data.phone,
            email=data.email,
            national_id=data.national_id,
            emergency_contact_name=data.emergency_contact_name,
            emergency_contact_phone=data.emergency_contact_phone,
            lease_start=data.lease_start,
            lease_end=data.lease_end,
            monthly_rent=data.monthly_rent,
            deposit_amount=dep,
            deposit_paid=bool(data.deposit_paid),
            deposit_receipt_path=data.deposit_receipt_path,
            status=st,
            notes=data.notes,
        )
        db.add(tenant)
        unit.status = UnitStatus.occupied
        db.commit()
        db.refresh(tenant)

        try:
            from app.models.notification import Notification, NotifType

            note = Notification(
                user_id=owner_id,
                title="New tenant added",
                message=f"{data.full_name} has been onboarded to unit {unit.unit_number}.",
                notif_type=NotifType.general,
                link=f"/landlord/tenants/{tenant.id}",
            )
            db.add(note)
            db.commit()
        except Exception:
            pass

        return self.get_tenant(db, tenant.id, owner_id)

    def update_tenant(self, db: Session, tenant_id: int, data: TenantUpdate, owner_id: int) -> dict:
        t = self._load(db, tenant_id, owner_id)
        payload = data.model_dump(exclude_none=True)
        if "status" in payload and payload["status"] is not None:
            try:
                t.status = TenantStatus(payload["status"])
            except ValueError:
                pass
            del payload["status"]
        for k, v in payload.items():
            if hasattr(t, k):
                setattr(t, k, v)
        db.commit()
        db.refresh(t)
        return self.get_tenant(db, tenant_id, owner_id)

    def move_out_tenant(self, db: Session, tenant_id: int, owner_id: int) -> dict:
        t = self._load(db, tenant_id, owner_id)
        t.status = TenantStatus.inactive
        if t.unit:
            t.unit.status = UnitStatus.vacant
        db.commit()
        db.refresh(t)
        return self.get_tenant(db, tenant_id, owner_id)


tenant_service = TenantService()
