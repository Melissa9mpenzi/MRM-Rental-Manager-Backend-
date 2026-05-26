"""Unified activity timeline for dashboards (audit, payments, compliance)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.payment import Payment, PaymentType
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User, UserRole, is_government_officer, is_system_admin


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_activity_feed(db: Session, user: User, *, limit: int = 25) -> list[dict[str, Any]]:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    events: list[dict[str, Any]] = []

    if is_system_admin(user.role) or is_government_officer(user.role):
        logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit * 2).all()
        for log in logs:
            detail = (log.new_value or log.old_value or "")[:200]
            agency = "platform"
            if "[NIRA]" in detail:
                agency = "nira"
            elif "[KCCA]" in detail:
                agency = "kcca"
            elif "[URA]" in detail or "tax" in (log.action or "").lower():
                agency = "ura"
            events.append(
                {
                    "id": f"audit-{log.id}",
                    "type": agency,
                    "title": (log.action or "system").replace("_", " ").title(),
                    "detail": detail,
                    "at": log.created_at.isoformat() if log.created_at else None,
                    "icon": "shield",
                }
            )
    elif role == UserRole.landlord.value:
        props = db.query(Property).filter(Property.owner_id == user.id).all()
        prop_ids = [p.id for p in props]
        if prop_ids:
            pays = (
                db.query(Payment)
                .filter(
                    Payment.owner_id == user.id,
                    Payment.is_deleted.is_(False),
                    Payment.payment_type == PaymentType.rent,
                )
                .order_by(Payment.payment_date.desc())
                .limit(12)
                .all()
            )
            for pay in pays:
                events.append(
                    {
                        "id": f"pay-{pay.id}",
                        "type": "payment",
                        "title": "Rent payment recorded",
                        "detail": f"UGX {float(pay.amount or 0):,.0f}",
                        "at": pay.payment_date.isoformat() if pay.payment_date else None,
                        "icon": "wallet",
                    }
                )
        for p in props:
            st = (p.gov_verification_status or "pending").lower()
            if st == "verified":
                events.append(
                    {
                        "id": f"kcca-{p.id}",
                        "type": "kcca",
                        "title": "KCCA approved property",
                        "detail": p.name,
                        "at": p.updated_at.isoformat() if p.updated_at else None,
                        "icon": "building",
                    }
                )
        events.append(
            {
                "id": f"nira-{user.id}",
                "type": "nira",
                "title": "Landlord identity verified",
                "detail": user.full_name,
                "at": user.kyc_submitted_at.isoformat() if user.kyc_submitted_at else None,
                "icon": "user",
            }
        )
    elif role == UserRole.tenant.value:
        tenant_rows = db.query(Tenant.id).filter(Tenant.user_id == user.id).all()
        tenant_ids = [t[0] for t in tenant_rows]
        pays = []
        if tenant_ids:
            pays = (
                db.query(Payment)
                .filter(Payment.tenant_id.in_(tenant_ids), Payment.is_deleted.is_(False))
                .order_by(Payment.payment_date.desc())
                .limit(10)
                .all()
            )
        for pay in pays:
            events.append(
                {
                    "id": f"pay-{pay.id}",
                    "type": "payment",
                    "title": "Rent paid",
                    "detail": f"UGX {float(pay.amount or 0):,.0f}",
                    "at": pay.payment_date.isoformat() if pay.payment_date else None,
                    "icon": "wallet",
                }
            )

    events.sort(key=lambda e: _parse_ts(e.get("at")) or datetime.min, reverse=True)
    return events[:limit]
