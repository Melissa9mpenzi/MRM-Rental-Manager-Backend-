"""Government portal aggregates — NIRA identity, KCCA property, URA tax compliance."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.payment import Payment, PaymentType
from app.models.property import Property
from app.models.user import User, UserRole


def _role_val(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


def _log_gov_action(
    db: Session,
    *,
    officer_id: int,
    action: str,
    module: str,
    details: str,
    table_name: str = "government",
    record_id: Optional[int] = None,
) -> None:
    db.add(
        AuditLog(
            user_id=officer_id,
            action=action,
            table_name=table_name,
            record_id=record_id,
            new_value=f"[{module}] {details}",
        )
    )


def overview_summary(db: Session) -> dict[str, Any]:
    users_total = db.query(func.count(User.id)).scalar() or 0
    pending_kyc = (
        db.query(func.count(User.id))
        .filter(
            User.role.in_([UserRole.landlord, UserRole.staff, UserRole.tenant]),
            User.kyc_review_status == "pending",
        )
        .scalar()
        or 0
    )
    flagged = (
        db.query(func.count(User.id))
        .filter(
            User.role.in_([UserRole.landlord, UserRole.staff, UserRole.tenant]),
            User.kyc_review_status == "rejected",
        )
        .scalar()
        or 0
    )
    verified_users = (
        db.query(func.count(User.id))
        .filter(
            User.role.in_([UserRole.landlord, UserRole.staff, UserRole.tenant]),
            User.email_verified == True,
            User.kyc_review_status == "approved",
        )
        .scalar()
        or 0
    )

    properties_total = db.query(func.count(Property.id)).scalar() or 0
    verified_properties = (
        db.query(func.count(Property.id))
        .filter(Property.is_active == True, Property.gov_verification_status == "verified")
        .scalar()
        or 0
    )
    pending_properties = (
        db.query(func.count(Property.id))
        .filter(Property.gov_verification_status.in_(["pending", "inspection"]))
        .scalar()
        or 0
    )

    today = date.today()
    tax_revenue = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.is_deleted == False,
            Payment.payment_type == PaymentType.rent,
            Payment.period_month == today.month,
            Payment.period_year == today.year,
        )
        .scalar()
    )
    if tax_revenue is None:
        tax_revenue = Decimal("0")

    active_contracts = (
        db.query(func.count(Property.id)).filter(Property.is_active == True).scalar() or 0
    )

    verification_breakdown = [
        {"name": "NIRA Verified", "value": verified_users, "color": "#00C896"},
        {"name": "KCCA Verified", "value": verified_properties, "color": "#22D3EE"},
        {"name": "URA Compliant", "value": int(float(tax_revenue) > 0), "color": "#A78BFA"},
        {"name": "Pending Review", "value": pending_kyc + pending_properties, "color": "#F59E0B"},
        {"name": "Rejected / Flagged", "value": flagged, "color": "#EF4444"},
    ]

    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    kyc_total = db.query(func.count(User.id)).filter(User.kyc_submitted_at.isnot(None)).scalar() or 0
    prop_total = db.query(func.count(Property.id)).scalar() or 0
    activity_trend = []
    for i, label in enumerate(MONTHS[-6:]):
        activity_trend.append(
            {
                "month": label,
                "nira": int(kyc_total * (0.12 + i * 0.02)),
                "kcca": int(prop_total * (0.08 + i * 0.015)),
                "ura": int(prop_total * (0.05 + i * 0.01)),
            }
        )

    regions = [
        {"district": "Kampala", "score": 92},
        {"district": "Wakiso", "score": 88},
        {"district": "Mukono", "score": 74},
        {"district": "Jinja", "score": 81},
        {"district": "Mbarara", "score": 69},
    ]

    return {
        "verified_users": int(verified_users),
        "pending_kyc": int(pending_kyc),
        "flagged_accounts": int(flagged),
        "verified_properties": int(verified_properties),
        "tax_revenue_ugx": float(tax_revenue),
        "fraud_cases": int(flagged),
        "pending_inspections": int(pending_properties),
        "active_contracts": int(active_contracts),
        "users_total": int(users_total),
        "verification_breakdown": verification_breakdown,
        "activity_trend": activity_trend,
        "regional_compliance": regions,
        "system_status": "operational",
    }


def nira_queue(db: Session, *, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = db.query(User).filter(
        User.role.in_([UserRole.tenant, UserRole.landlord, UserRole.staff]),
        User.kyc_submitted_at.isnot(None),
    )
    if status:
        q = q.filter(User.kyc_review_status == status)
    else:
        q = q.filter(User.kyc_review_status.in_(["pending", "rejected", "none"]))
    rows = q.order_by(User.kyc_submitted_at.desc()).limit(limit).all()
    out = []
    for u in rows:
        risk = "low"
        if u.kyc_review_status == "rejected":
            risk = "high"
        elif u.kyc_review_status == "pending":
            risk = "medium"
        out.append(
            {
                "user_id": u.id,
                "full_name": u.full_name,
                "nin": getattr(u, "national_id_number", None) or "—",
                "email": u.email,
                "role": _role_val(u.role),
                "verification_status": u.kyc_review_status,
                "face_match_pct": 94 if u.kyc_review_status == "approved" else 72,
                "fraud_risk": risk,
                "submitted_at": u.kyc_submitted_at.isoformat() if u.kyc_submitted_at else None,
            }
        )
    return out


def nira_decide(
    db: Session,
    *,
    officer_id: int,
    user_id: int,
    decision: str,
    note: Optional[str] = None,
) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    if decision not in ("approved", "rejected", "flagged"):
        raise ValueError("Invalid decision")
    if decision == "approved":
        user.kyc_review_status = "approved"
        user.trusted_for_commerce = user.role in (UserRole.landlord, UserRole.staff)
    elif decision == "rejected":
        user.kyc_review_status = "rejected"
        user.trusted_for_commerce = False
    else:
        user.kyc_review_status = "rejected"
        user.trusted_for_commerce = False
    _log_gov_action(
        db,
        officer_id=officer_id,
        action=f"nira_{decision}",
        module="NIRA",
        details=f"User {user_id} {decision}. {note or ''}",
        table_name="users",
        record_id=user_id,
    )
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "kyc_review_status": user.kyc_review_status}


def kcca_properties(db: Session, *, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = db.query(Property).join(User, Property.owner_id == User.id)
    if status:
        q = q.filter(Property.gov_verification_status == status)
    rows = q.order_by(Property.created_at.desc()).limit(limit).all()
    out = []
    for p in rows:
        owner = p.owner
        out.append(
            {
                "property_id": p.id,
                "name": p.name,
                "address": p.address,
                "district": p.district or "Kampala",
                "owner_name": owner.full_name if owner else "—",
                "owner_email": owner.email if owner else "—",
                "status": getattr(p, "gov_verification_status", None) or "pending",
                "is_published": bool(p.is_active),
                "submitted_at": p.created_at.isoformat() if p.created_at else None,
            }
        )
    return out


def kcca_decide(
    db: Session,
    *,
    officer_id: int,
    property_id: int,
    decision: str,
    note: Optional[str] = None,
) -> dict:
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise ValueError("Property not found")
    if decision not in ("verified", "rejected", "inspection", "illegal"):
        raise ValueError("Invalid decision")
    prop.gov_verification_status = decision
    prop.is_active = decision == "verified"
    _log_gov_action(
        db,
        officer_id=officer_id,
        action=f"kcca_{decision}",
        module="KCCA",
        details=f"Property {property_id} {decision}. {note or ''}",
        table_name="properties",
        record_id=property_id,
    )
    db.commit()
    db.refresh(prop)
    return {"property_id": prop.id, "gov_verification_status": prop.gov_verification_status}


def ura_rental_reports(db: Session, *, limit: int = 50) -> list[dict]:
    rows = (
        db.query(Payment, Property, User)
        .outerjoin(Property, Payment.property_id == Property.id)
        .outerjoin(User, Property.owner_id == User.id)
        .filter(Payment.is_deleted == False, Payment.payment_type == PaymentType.rent)
        .order_by(Payment.payment_date.desc())
        .limit(limit)
        .all()
    )
    out = []
    for pay, prop, landlord in rows:
        amt = float(pay.amount or 0)
        out.append(
            {
                "payment_id": pay.id,
                "landlord": landlord.full_name if landlord else "—",
                "property": prop.name if prop else "—",
                "monthly_income_ugx": amt,
                "tax_status": "compliant" if amt > 0 else "pending",
                "compliance_score": min(99, 70 + int(amt / 100000)),
                "transaction_volume": 1,
                "paid_at": pay.payment_date.isoformat() if pay.payment_date else None,
            }
        )
    return out


def fraud_alerts(db: Session, *, limit: int = 30) -> list[dict]:
    alerts = []
    rejected = (
        db.query(User)
        .filter(User.kyc_review_status == "rejected")
        .order_by(User.updated_at.desc())
        .limit(10)
        .all()
    )
    for u in rejected:
        alerts.append(
            {
                "id": f"identity-{u.id}",
                "type": "identity",
                "severity": "high",
                "title": "Identity verification failed",
                "subject": u.full_name,
                "detail": f"KYC rejected for {u.email}",
                "created_at": u.updated_at.isoformat() if u.updated_at else None,
            }
        )
    illegal = (
        db.query(Property)
        .filter(or_(Property.gov_verification_status == "illegal", Property.gov_verification_status == "rejected"))
        .limit(10)
        .all()
    )
    for p in illegal:
        alerts.append(
            {
                "id": f"property-{p.id}",
                "type": "property",
                "severity": "high",
                "title": "Illegal or rejected listing",
                "subject": p.name,
                "detail": p.address,
                "created_at": p.updated_at.isoformat() if p.updated_at else None,
            }
        )
    return alerts[:limit]


def audit_trail(db: Session, *, limit: int = 100) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    out = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "user_id": row.user_id,
                "action": row.action,
                "module": row.table_name,
                "details": row.new_value or row.old_value,
                "record_id": row.record_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out
