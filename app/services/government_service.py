"""Government portal aggregates — NIRA identity, KCCA property, URA tax compliance."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.audit import AuditLog
from app.models.payment import Payment, PaymentType
from app.models.property import Property
from app.models.user import User, UserRole
from app.services.blockchain import walrus_anchor_service
from app.services.kyc_service import reconcile_all_pending_kyc_uploads


def _role_val(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


def agency_for_user(user: User) -> str:
    """nira | kcca | ura | all (system administrator)."""
    role = _role_val(user.role)
    if role == UserRole.system_admin.value:
        return "all"
    if role == UserRole.gov_nira.value:
        return "nira"
    if role == UserRole.gov_kcca.value:
        return "kcca"
    if role == UserRole.gov_ura.value:
        return "ura"
    return "all"


def _normalize_district(name: Optional[str]) -> str:
    raw = (name or "").strip() or "Unknown"
    known = {
        "kampala": "Kampala",
        "wakiso": "Wakiso",
        "mukono": "Mukono",
        "jinja": "Jinja",
        "gulu": "Gulu",
        "mbarara": "Mbarara",
        "entebbe": "Entebbe",
        "mbale": "Mbale",
        "masaka": "Masaka",
    }
    return known.get(raw.lower(), raw.title() if raw else "Unknown")


def _regional_compliance_db(db: Session, *, agency: str = "all") -> list[dict]:
    """District compliance from live property (and payment) data."""
    districts: dict[str, dict] = {}

    props = (
        db.query(Property.district, Property.gov_verification_status, func.count(Property.id))
        .group_by(Property.district, Property.gov_verification_status)
        .all()
    )
    for district, status, cnt in props:
        name = _normalize_district(district)
        if name not in districts:
            districts[name] = {"total": 0, "verified": 0, "pending": 0}
        districts[name]["total"] += int(cnt or 0)
        if status == "verified":
            districts[name]["verified"] += int(cnt or 0)
        elif status in ("pending", "inspection"):
            districts[name]["pending"] += int(cnt or 0)

    if agency == "ura":
        pay_rows = (
            db.query(Property.district, func.count(Payment.id))
            .join(Property, Payment.property_id == Property.id)
            .filter(
                Payment.is_deleted == False,
                Payment.payment_type == PaymentType.rent,
            )
            .group_by(Property.district)
            .all()
        )
        for district, cnt in pay_rows:
            name = _normalize_district(district)
            if name not in districts:
                districts[name] = {"total": 0, "verified": 0, "pending": 0}
            districts[name]["verified"] = max(districts[name]["verified"], int(cnt or 0))

    if not districts:
        return []

    out = []
    for district, stats in districts.items():
        total = max(stats["total"], 1)
        if agency == "nira":
            score = min(99, 60 + int(100 * stats["verified"] / total))
        elif agency == "ura":
            score = min(99, 55 + int(100 * stats["verified"] / total))
        else:
            score = min(99, int(100 * stats["verified"] / total))
        out.append(
            {
                "district": district,
                "score": score,
                "count": stats["total"],
                "properties": stats["total"],
                "pending": stats["pending"],
            }
        )
    out.sort(key=lambda x: (-x["score"], -x["count"]))
    return out[:12]


def _last_six_month_buckets(today: date) -> list[tuple[datetime, datetime, str]]:
    """Return (start, end, label) for each of the last six calendar months."""
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    buckets: list[tuple[datetime, datetime, str]] = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start_dt = datetime(y, m, 1)
        if m == 12:
            end_dt = datetime(y + 1, 1, 1)
        else:
            end_dt = datetime(y, m + 1, 1)
        buckets.append((start_dt, end_dt, MONTHS[m - 1]))
    return buckets


def _build_activity_trend(db: Session) -> list[dict[str, Any]]:
    """Monthly activity from KYC submissions, new properties, and rent volume."""
    trend: list[dict[str, Any]] = []
    for start_dt, end_dt, label in _last_six_month_buckets(date.today()):
        nira = (
            db.query(func.count(User.id))
            .filter(User.kyc_submitted_at >= start_dt, User.kyc_submitted_at < end_dt)
            .scalar()
            or 0
        )
        kcca = (
            db.query(func.count(Property.id))
            .filter(Property.created_at >= start_dt, Property.created_at < end_dt)
            .scalar()
            or 0
        )
        m, y = start_dt.month, start_dt.year
        ura_val = (
            db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(
                Payment.is_deleted == False,
                Payment.payment_type == PaymentType.rent,
                Payment.period_month == int(m),
                Payment.period_year == int(y),
            )
            .scalar()
        )
        if ura_val is None:
            ura_val = Decimal("0")
        trend.append(
            {
                "month": label,
                "nira": int(nira),
                "kcca": int(kcca),
                "ura": int(float(ura_val)),
            }
        )
    return trend


def _log_gov_action(
    db: Session,
    *,
    officer_id: int,
    action: str,
    module: str,
    details: str,
    table_name: str = "government",
    record_id: Optional[int] = None,
) -> AuditLog:
    log = AuditLog(
        user_id=officer_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        new_value=f"[{module}] {details}",
    )
    db.add(log)
    db.flush()
    officer = db.query(User).filter(User.id == officer_id).first()
    walrus_anchor_service.anchor_audit_log(
        db,
        log,
        actor_name=officer.full_name if officer else None,
    )
    return log


def overview_summary(db: Session, *, agency: str = "all") -> dict[str, Any]:
    agency = (agency or "all").lower()
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
        {"name": "Verified", "value": int(verified_users), "color": "#00C896"},
        {"name": "Pending KYC", "value": int(pending_kyc), "color": "#A78BFA"},
        {"name": "Rejected", "value": int(flagged), "color": "#EF4444"},
    ]

    activity_trend = _build_activity_trend(db)

    rent_payments_mtd = (
        db.query(func.count(Payment.id))
        .filter(
            Payment.is_deleted == False,
            Payment.payment_type == PaymentType.rent,
            Payment.period_month == today.month,
            Payment.period_year == today.year,
        )
        .scalar()
        or 0
    )

    regions = _regional_compliance_db(db, agency=agency)

    payload: dict[str, Any] = {
        "agency": agency,
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

    if agency == "nira":
        payload["verification_breakdown"] = [
            {"name": "Verified", "value": int(verified_users), "color": "#00C896"},
            {"name": "Pending KYC", "value": int(pending_kyc), "color": "#A78BFA"},
            {"name": "Rejected", "value": int(flagged), "color": "#EF4444"},
        ]
        payload["activity_trend"] = [{"month": t["month"], "nira": t["nira"]} for t in activity_trend]
    elif agency == "kcca":
        payload["verification_breakdown"] = [
            {"name": "Verified", "value": int(verified_properties), "color": "#22D3EE"},
            {"name": "Pending", "value": int(pending_properties), "color": "#F59E0B"},
            {
                "name": "Rejected / Illegal",
                "value": max(0, int(properties_total) - int(verified_properties) - int(pending_properties)),
                "color": "#EF4444",
            },
        ]
        payload["activity_trend"] = [{"month": t["month"], "kcca": t["kcca"]} for t in activity_trend]
    elif agency == "ura":
        payload["verification_breakdown"] = [
            {"name": "Compliant", "value": int(rent_payments_mtd), "color": "#EAB308"},
            {"name": "Pending", "value": int(pending_kyc), "color": "#A78BFA"},
            {"name": "Under review", "value": int(pending_properties), "color": "#22D3EE"},
        ]
        payload["activity_trend"] = [{"month": t["month"], "ura": t["ura"]} for t in activity_trend]

    return payload


def _pending_kyc_count(db: Session) -> int:
    return (
        db.query(func.count(User.id))
        .filter(
            User.role.in_([UserRole.tenant, UserRole.landlord, UserRole.staff]),
            func.lower(User.kyc_review_status) == "pending",
        )
        .scalar()
        or 0
    )


def nira_queue(
    db: Session,
    *,
    status: Optional[str] = None,
    limit: int = 100,
    search: Optional[str] = None,
) -> dict[str, Any]:
    """Landlord/agent/tenant KYC queue — same records as platform 'pending verification' banners."""
    repaired = reconcile_all_pending_kyc_uploads(db)

    q = db.query(User).filter(
        User.role.in_([UserRole.tenant, UserRole.landlord, UserRole.staff]),
    )
    if status:
        q = q.filter(func.lower(User.kyc_review_status) == status.lower().strip())
    else:
        q = q.filter(func.lower(User.kyc_review_status).in_(["pending", "approved", "rejected"]))
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(User.email.ilike(term), User.full_name.ilike(term)))
    rows = (
        q.order_by(User.kyc_submitted_at.asc().nullsfirst(), User.id.asc())
        .limit(min(limit, 200))
        .all()
    )
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
                **walrus_anchor_service.proof_fields(getattr(u, "kyc_walrus_blob_id", None)),
                "kyc_manifest_hash": getattr(u, "kyc_manifest_hash", None),
            }
        )
    return {
        "items": out,
        "pending_in_database": _pending_kyc_count(db),
        "repaired_from_uploads": repaired,
        "environment": settings.environment,
    }


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
    walrus_anchor_service.anchor_kyc_decision(
        db,
        user,
        officer_id=officer_id,
        decision=decision,
        note=note,
    )
    db.commit()
    db.refresh(user)
    return {
        "user_id": user.id,
        "kyc_review_status": user.kyc_review_status,
        **walrus_anchor_service.proof_fields(user.kyc_walrus_blob_id),
    }


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
                **walrus_anchor_service.proof_fields(getattr(p, "gov_walrus_blob_id", None)),
                "gov_packet_hash": getattr(p, "gov_packet_hash", None),
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
    if decision == "verified":
        prop.is_active = True
    elif decision in ("rejected", "illegal"):
        prop.is_active = False
    _log_gov_action(
        db,
        officer_id=officer_id,
        action=f"kcca_{decision}",
        module="KCCA",
        details=f"Property {property_id} {decision}. {note or ''}",
        table_name="properties",
        record_id=property_id,
    )
    walrus_anchor_service.anchor_property_decision(
        db,
        prop,
        officer_id=officer_id,
        decision=decision,
        note=note,
    )
    db.commit()
    db.refresh(prop)
    return {
        "property_id": prop.id,
        "gov_verification_status": prop.gov_verification_status,
        **walrus_anchor_service.proof_fields(prop.gov_walrus_blob_id),
    }


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


def fraud_alerts(db: Session, *, agency: str = "all", limit: int = 30) -> list[dict]:
    agency = (agency or "all").lower()
    alerts = []
    rejected = (
        db.query(User)
        .filter(User.kyc_review_status == "rejected")
        .order_by(User.updated_at.desc())
        .limit(10)
        .all()
    )
    if agency in ("all", "nira"):
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
    if agency in ("all", "kcca"):
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
                    "detail": p.address or p.district,
                    "created_at": p.updated_at.isoformat() if p.updated_at else None,
                }
            )
    if agency in ("all", "ura"):
        pending_tax = (
            db.query(Payment, Property, User)
            .outerjoin(Property, Payment.property_id == Property.id)
            .outerjoin(User, Property.owner_id == User.id)
            .filter(Payment.is_deleted == False, Payment.payment_type == PaymentType.rent)
            .order_by(Payment.payment_date.desc())
            .limit(8)
            .all()
        )
        for pay, prop, landlord in pending_tax:
            if float(pay.amount or 0) <= 0:
                continue
            alerts.append(
                {
                    "id": f"tax-{pay.id}",
                    "type": "tax",
                    "severity": "medium",
                    "title": "Rental income requires tax review",
                    "subject": landlord.full_name if landlord else "Landlord",
                    "detail": f"{prop.name if prop else 'Property'} · UGX {float(pay.amount or 0):,.0f}",
                    "created_at": pay.payment_date.isoformat() if pay.payment_date else None,
                }
            )
    return alerts[:limit]


def _audit_module_tag(agency: str) -> str:
    return {"nira": "[NIRA]", "kcca": "[KCCA]", "ura": "[URA]"}.get(agency, "")


def audit_trail(db: Session, *, agency: str = "all", limit: int = 100) -> list[dict]:
    q = (
        db.query(AuditLog, User)
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc())
    )
    agency = (agency or "all").lower()
    tag = _audit_module_tag(agency)
    if tag:
        q = q.filter(
            or_(
                AuditLog.new_value.ilike(f"%{tag}%"),
                AuditLog.action.ilike(f"{agency}_%"),
            )
        )
    rows = q.limit(limit).all()
    out = []
    for log, actor in rows:
        out.append(
            {
                "id": log.id,
                "user_id": log.user_id,
                "user": actor.full_name if actor else ("System" if not log.user_id else f"Officer #{log.user_id}"),
                "action": log.action,
                "module": log.table_name,
                "details": log.new_value or log.old_value,
                "record_id": log.record_id,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                **walrus_anchor_service.proof_fields(getattr(log, "walrus_blob_id", None)),
            }
        )
    return out


def nira_blacklist(db: Session, *, limit: int = 50) -> list[dict]:
    """Suspended / high-risk accounts (NIRA fraud prevention)."""
    rows = (
        db.query(User)
        .filter(
            User.role.in_([UserRole.tenant, UserRole.landlord, UserRole.staff]),
            or_(
                User.gov_suspended.is_(True),
                User.kyc_review_status == "rejected",
            ),
        )
        .order_by(User.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "user_id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "role": _role_val(u.role),
            "kyc_review_status": u.kyc_review_status,
            "gov_suspended": bool(u.gov_suspended),
            "reason": u.gov_suspension_reason or (
                "KYC rejected" if u.kyc_review_status == "rejected" else "—"
            ),
            "suspended_at": u.gov_suspended_at.isoformat() if u.gov_suspended_at else None,
        }
        for u in rows
    ]


def nira_suspend_user(
    db: Session,
    *,
    officer_id: int,
    user_id: int,
    reason: str,
) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    if user.role in (UserRole.gov_nira, UserRole.gov_kcca, UserRole.gov_ura, UserRole.system_admin):
        raise ValueError("Government and system accounts cannot be blacklisted via this action.")
    user.gov_suspended = True
    user.is_active = False
    user.trusted_for_commerce = False
    user.gov_suspension_reason = (reason or "Suspended by NIRA officer.").strip()[:500]
    user.gov_suspended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _log_gov_action(
        db,
        officer_id=officer_id,
        action="nira_blacklist",
        module="NIRA",
        details=f"Suspended user {user_id} ({user.email}): {user.gov_suspension_reason}",
        table_name="users",
        record_id=user_id,
    )
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "gov_suspended": True}


def nira_unsuspend_user(db: Session, *, officer_id: int, user_id: int) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")
    user.gov_suspended = False
    user.is_active = True
    user.gov_suspension_reason = None
    user.gov_suspended_at = None
    _log_gov_action(
        db,
        officer_id=officer_id,
        action="nira_unsuspend",
        module="NIRA",
        details=f"Removed suspension for user {user_id} ({user.email})",
        table_name="users",
        record_id=user_id,
    )
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "gov_suspended": False}


def government_workflow_summary() -> dict[str, Any]:
    """National compliance pipeline for officer onboarding UI."""
    return {
        "title": "RentDirect UG — Government compliance workflow",
        "steps": [
            {
                "order": 1,
                "agency": "NIRA",
                "label": "Identity verification",
                "description": "User registers → NIRA verifies ID, face match, KYC → Approve / Reject / Blacklist",
            },
            {
                "order": 2,
                "agency": "KCCA",
                "label": "Property compliance",
                "description": "Landlord lists property → KCCA verifies legality & location → Approve listing",
            },
            {
                "order": 3,
                "agency": "URA",
                "label": "Tax compliance",
                "description": "Rent is paid → URA monitors revenue & tax reporting",
            },
        ],
        "badges": [
            {"key": "nira_verified_landlord", "label": "NIRA Verified Landlord"},
            {"key": "kcca_approved_property", "label": "KCCA Approved Property"},
            {"key": "ura_compliant", "label": "URA Compliant"},
        ],
    }
