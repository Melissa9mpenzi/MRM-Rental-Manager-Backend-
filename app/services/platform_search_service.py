"""Global search — role-scoped users, properties, payments."""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User, UserRole, is_government_officer, is_system_admin


def global_search(db: Session, user: User, *, q: str, limit: int = 12) -> dict[str, list[dict[str, Any]]]:
    term = (q or "").strip()
    if len(term) < 2:
        return {"users": [], "properties": [], "payments": [], "tenants": []}

    like = f"%{term}%"
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    out: dict[str, list[dict[str, Any]]] = {
        "users": [],
        "properties": [],
        "payments": [],
        "tenants": [],
    }

    if is_system_admin(user.role):
        users = (
            db.query(User)
            .filter(or_(User.email.ilike(like), User.full_name.ilike(like)))
            .limit(limit)
            .all()
        )
        out["users"] = [
            {
                "id": u.id,
                "label": u.full_name,
                "sub": u.email,
                "kind": "user",
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            }
            for u in users
        ]
        props = (
            db.query(Property)
            .filter(or_(Property.name.ilike(like), Property.address.ilike(like), Property.district.ilike(like)))
            .limit(limit)
            .all()
        )
    elif is_government_officer(user.role):
        props = (
            db.query(Property)
            .filter(or_(Property.name.ilike(like), Property.address.ilike(like), Property.district.ilike(like)))
            .limit(limit)
            .all()
        )
        users = (
            db.query(User)
            .filter(
                User.role.in_([UserRole.landlord, UserRole.staff, UserRole.tenant]),
                or_(User.email.ilike(like), User.full_name.ilike(like)),
            )
            .limit(limit)
            .all()
        )
        out["users"] = [
            {
                "id": u.id,
                "label": u.full_name,
                "sub": f"{u.email} · {u.kyc_review_status}",
                "kind": "user",
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            }
            for u in users
        ]
    elif role == UserRole.landlord.value:
        props = (
            db.query(Property)
            .filter(
                Property.owner_id == user.id,
                or_(Property.name.ilike(like), Property.address.ilike(like)),
            )
            .limit(limit)
            .all()
        )
        tenants = (
            db.query(Tenant)
            .join(Property, Tenant.property_id == Property.id)
            .filter(Property.owner_id == user.id, Tenant.full_name.ilike(like))
            .limit(limit)
            .all()
        )
        out["tenants"] = [
            {"id": t.id, "label": t.full_name, "sub": t.email or "Tenant", "kind": "tenant"}
            for t in tenants
        ]
    else:
        props = (
            db.query(Property)
            .filter(
                Property.is_active.is_(True),
                Property.gov_verification_status == "verified",
                or_(Property.name.ilike(like), Property.address.ilike(like), Property.district.ilike(like)),
            )
            .limit(limit)
            .all()
        )

    out["properties"] = [
        {
            "id": p.id,
            "label": p.name,
            "sub": f"{p.district} · {p.gov_verification_status}",
            "kind": "property",
        }
        for p in props
    ]

    if role in (UserRole.landlord.value, UserRole.system_admin.value):
        pay_q = db.query(Payment).filter(Payment.is_deleted.is_(False))
        if role == UserRole.landlord.value:
            pay_q = pay_q.filter(Payment.owner_id == user.id)
        pays = (
            pay_q.filter(or_(Payment.reference.ilike(like), Payment.notes.ilike(like)))
            .order_by(Payment.payment_date.desc())
            .limit(limit)
            .all()
        )
        out["payments"] = [
            {
                "id": pay.id,
                "label": f"Payment #{pay.id}",
                "sub": f"UGX {float(pay.amount or 0):,.0f}",
                "kind": "payment",
            }
            for pay in pays[:limit]
        ]

    return out
