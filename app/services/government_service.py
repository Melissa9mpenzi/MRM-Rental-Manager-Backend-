"""Government portal aggregates — NIRA identity, KCCA property, URA tax compliance."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from functools import lru_cache

from sqlalchemy import String, cast, func, or_, true
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, aliased

from app.config import settings
from app.database import engine, postgres_table_schema
from app.models.audit import AuditLog
from app.models.lease import Lease, LeaseStatus
from app.models.payment import Payment, PaymentType
from app.models.property import Property, Unit
from app.models.user import User, UserRole
from app.services.blockchain import walrus_anchor_service
from app.services.kyc_service import reconcile_all_pending_kyc_uploads


def _role_val(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


@lru_cache(maxsize=1)
def _table_columns(table: str) -> frozenset[str]:
    insp = sa_inspect(engine)
    schema = postgres_table_schema
    try:
        if not insp.has_table(table, schema=schema):
            return frozenset()
        return frozenset(
            c["name"] for c in insp.get_columns(table, schema=schema)
        )
    except Exception:  # noqa: BLE001
        return frozenset()


def _payment_not_deleted():
    if "is_deleted" in _table_columns("payments"):
        return Payment.is_deleted.is_(False)
    return true()


def _rent_payment_type_filter():
    """Match rent rows whether payment_type is a PG enum or legacy VARCHAR."""
    return or_(
        Payment.payment_type == PaymentType.rent,
        cast(Payment.payment_type, String) == PaymentType.rent.value,
    )


def _property_gov_status_column():
    return getattr(Property, "gov_verification_status", None)


def _kyc_face_match_pct(_user: User) -> int | None:
    """No in-app biometric engine yet — officers use documents + Walrus manifest, not a fake %."""
    return None


def _ura_compliance_from_payment(pay: Payment) -> tuple[str, int | None]:
    """Tax compliance from payment fields only — no synthetic score formula."""
    amt = float(pay.amount or 0)
    ref = (pay.reference or "").strip()
    if amt <= 0:
        return "pending", None
    if ref:
        return "compliant", 100
    return "under_review", None


def _payment_property_user_query(db: Session):
    """Payment → Unit (direct or via lease) → Property → landlord User."""
    unit_direct = aliased(Unit)
    unit_lease = aliased(Unit)
    return (
        db.query(Payment, Property, User)
        .outerjoin(unit_direct, Payment.unit_id == unit_direct.id)
        .outerjoin(Lease, Payment.lease_id == Lease.id)
        .outerjoin(unit_lease, Lease.unit_id == unit_lease.id)
        .outerjoin(
            Property,
            or_(
                unit_direct.property_id == Property.id,
                unit_lease.property_id == Property.id,
            ),
        )
        .outerjoin(User, Property.owner_id == User.id)
    )


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
    gov_col = _property_gov_status_column()

    if gov_col is not None:
        props = (
            db.query(Property.district, gov_col, func.count(Property.id))
            .group_by(Property.district, gov_col)
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
    else:
        props = (
            db.query(Property.district, func.count(Property.id))
            .group_by(Property.district)
            .all()
        )
        for district, cnt in props:
            name = _normalize_district(district)
            districts[name] = {"total": int(cnt or 0), "verified": 0, "pending": int(cnt or 0)}

    if agency == "ura":
        pay_rows = (
            db.query(Property.district, func.count(Payment.id))
            .join(Unit, Payment.unit_id == Unit.id)
            .join(Property, Unit.property_id == Property.id)
            .filter(_payment_not_deleted(), _rent_payment_type_filter())
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
    user_cols = _table_columns("users")
    has_kyc_submitted = "kyc_submitted_at" in user_cols
    for start_dt, end_dt, label in _last_six_month_buckets(date.today()):
        if has_kyc_submitted:
            nira = (
                db.query(func.count(User.id))
                .filter(User.kyc_submitted_at >= start_dt, User.kyc_submitted_at < end_dt)
                .scalar()
                or 0
            )
        else:
            nira = 0
        kcca = (
            db.query(func.count(Property.id))
            .filter(Property.created_at >= start_dt, Property.created_at < end_dt)
            .scalar()
            or 0
        )
        m, y = start_dt.month, start_dt.year
        pay_filters = [_payment_not_deleted(), _rent_payment_type_filter()]
        if "period_month" in _table_columns("payments"):
            pay_filters.extend(
                [Payment.period_month == int(m), Payment.period_year == int(y)]
            )
        ura_val = (
            db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(*pay_filters)
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
    gov_col = _property_gov_status_column()
    if gov_col is not None:
        verified_properties = (
            db.query(func.count(Property.id))
            .filter(Property.is_active == True, gov_col == "verified")
            .scalar()
            or 0
        )
        pending_properties = (
            db.query(func.count(Property.id))
            .filter(gov_col.in_(["pending", "inspection"]))
            .scalar()
            or 0
        )
    else:
        verified_properties = (
            db.query(func.count(Property.id)).filter(Property.is_active == True).scalar() or 0
        )
        pending_properties = max(0, int(properties_total) - int(verified_properties))

    today = date.today()
    tax_filters = [_payment_not_deleted(), _rent_payment_type_filter()]
    if "period_month" in _table_columns("payments"):
        tax_filters.extend(
            [Payment.period_month == today.month, Payment.period_year == today.year]
        )
    tax_revenue = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(*tax_filters)
        .scalar()
    )
    if tax_revenue is None:
        tax_revenue = Decimal("0")

    active_contracts = (
        db.query(func.count(Lease.id))
        .filter(Lease.status.in_([LeaseStatus.active, LeaseStatus.pending]))
        .scalar()
        or 0
    )

    verification_breakdown = [
        {"name": "Verified", "value": int(verified_users), "color": "#00C896"},
        {"name": "Pending KYC", "value": int(pending_kyc), "color": "#A78BFA"},
        {"name": "Rejected", "value": int(flagged), "color": "#EF4444"},
    ]

    activity_trend = _build_activity_trend(db)

    mtd_filters = list(tax_filters)
    rent_payments_mtd = (
        db.query(func.count(Payment.id)).filter(*mtd_filters).scalar() or 0
    )

    regions = _regional_compliance_db(db, agency=agency)

    payload: dict[str, Any] = {
        "data_source": "database",
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
                "face_match_pct": _kyc_face_match_pct(u),
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
        _payment_property_user_query(db)
        .filter(_payment_not_deleted(), _rent_payment_type_filter())
        .order_by(Payment.payment_date.desc())
        .limit(limit)
        .all()
    )
    out = []
    for pay, prop, landlord in rows:
        amt = float(pay.amount or 0)
        tax_status, compliance_score = _ura_compliance_from_payment(pay)
        out.append(
            {
                "payment_id": pay.id,
                "landlord": landlord.full_name if landlord else "—",
                "property": prop.name if prop else "—",
                "monthly_income_ugx": amt,
                "tax_status": tax_status,
                "compliance_score": compliance_score,
                "transaction_volume": 1,
                "paid_at": pay.payment_date.isoformat() if pay.payment_date else None,
                "payment_reference": pay.reference,
            }
        )
    return out


def _identity_fraud_alerts(db: Session, *, limit_each: int = 12) -> list[dict]:
    """NIRA-facing identity / KYC risk signals from live user records."""
    commerce_roles = [UserRole.landlord, UserRole.staff, UserRole.tenant]
    alerts: list[dict] = []
    user_cols = _table_columns("users")
    has_submitted = "kyc_submitted_at" in user_cols
    has_suspended = "gov_suspended" in user_cols

    if has_suspended:
        suspended = (
            db.query(User)
            .filter(
                User.role.in_(commerce_roles),
                User.gov_suspended.is_(True),
            )
            .order_by(User.gov_suspended_at.desc().nullslast(), User.updated_at.desc())
            .limit(limit_each)
            .all()
        )
        for u in suspended:
            reason = (u.gov_suspension_reason or "Suspended by NIRA officer.").strip()
            alerts.append(
                {
                    "id": f"suspended-{u.id}",
                    "type": "identity",
                    "severity": "high",
                    "title": "Account suspended",
                    "subject": u.full_name,
                    "detail": f"{u.email} · {reason[:120]}",
                    "created_at": (
                        u.gov_suspended_at.isoformat()
                        if u.gov_suspended_at
                        else (u.updated_at.isoformat() if u.updated_at else None)
                    ),
                    "user_id": u.id,
                }
            )

    rejected = (
        db.query(User)
        .filter(User.role.in_(commerce_roles), User.kyc_review_status == "rejected")
        .order_by(User.updated_at.desc())
        .limit(limit_each)
        .all()
    )
    for u in rejected:
        alerts.append(
            {
                "id": f"identity-rejected-{u.id}",
                "type": "identity",
                "severity": "high",
                "title": "Identity verification failed",
                "subject": u.full_name,
                "detail": f"KYC rejected · {u.email}",
                "created_at": u.updated_at.isoformat() if u.updated_at else None,
                "user_id": u.id,
            }
        )

    pending = (
        db.query(User)
        .filter(User.role.in_(commerce_roles), User.kyc_review_status == "pending")
        .order_by(
            User.kyc_submitted_at.desc().nullslast() if has_submitted else User.updated_at.desc(),
            User.id.asc(),
        )
        .limit(limit_each)
        .all()
    )
    for u in pending:
        submitted = (
            u.kyc_submitted_at.strftime("%d %b %Y")
            if has_submitted and u.kyc_submitted_at
            else "awaiting documents"
        )
        alerts.append(
            {
                "id": f"identity-pending-{u.id}",
                "type": "identity",
                "severity": "medium",
                "title": "KYC pending officer review",
                "subject": u.full_name,
                "detail": f"{_role_val(u.role)} · {u.email} · submitted {submitted}",
                "created_at": (
                    u.kyc_submitted_at.isoformat()
                    if has_submitted and u.kyc_submitted_at
                    else (u.updated_at.isoformat() if u.updated_at else None)
                ),
                "user_id": u.id,
            }
        )

    incomplete = (
        db.query(User)
        .filter(
            User.role.in_([UserRole.landlord, UserRole.staff]),
            func.lower(User.kyc_review_status).in_(["none", ""]),
        )
        .order_by(User.created_at.desc())
        .limit(limit_each)
        .all()
    )
    for u in incomplete:
        alerts.append(
            {
                "id": f"identity-incomplete-{u.id}",
                "type": "identity",
                "severity": "low",
                "title": "KYC not submitted",
                "subject": u.full_name,
                "detail": f"{_role_val(u.role)} · {u.email} — no verification packet yet",
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "user_id": u.id,
            }
        )

    return alerts


def _property_fraud_alerts(db: Session, *, limit_each: int = 12) -> list[dict]:
    """KCCA-facing property compliance risk signals."""
    alerts: list[dict] = []
    gov_col = _property_gov_status_column()

    if gov_col is not None:
        high_risk = (
            db.query(Property)
            .filter(gov_col.in_(["illegal", "rejected"]))
            .order_by(Property.updated_at.desc())
            .limit(limit_each)
            .all()
        )
        for p in high_risk:
            alerts.append(
                {
                    "id": f"property-{p.id}",
                    "type": "property",
                    "severity": "high",
                    "title": "Illegal or rejected listing",
                    "subject": p.name,
                    "detail": p.address or p.district or "—",
                    "created_at": p.updated_at.isoformat() if p.updated_at else None,
                    "property_id": p.id,
                }
            )

        pending = (
            db.query(Property)
            .filter(gov_col.in_(["pending", "inspection"]))
            .order_by(Property.created_at.desc())
            .limit(limit_each)
            .all()
        )
        for p in pending:
            status = getattr(p, "gov_verification_status", None) or "pending"
            alerts.append(
                {
                    "id": f"property-pending-{p.id}",
                    "type": "property",
                    "severity": "medium",
                    "title": "Property awaiting KCCA verification",
                    "subject": p.name,
                    "detail": f"{p.district or 'Kampala'} · status {status}",
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "property_id": p.id,
                }
            )
    else:
        inactive = (
            db.query(Property)
            .filter(Property.is_active == False)
            .order_by(Property.updated_at.desc())
            .limit(limit_each)
            .all()
        )
        for p in inactive:
            alerts.append(
                {
                    "id": f"property-inactive-{p.id}",
                    "type": "property",
                    "severity": "medium",
                    "title": "Inactive property listing",
                    "subject": p.name,
                    "detail": p.address or p.district or "—",
                    "created_at": p.updated_at.isoformat() if p.updated_at else None,
                    "property_id": p.id,
                }
            )

    return alerts


def fraud_alerts(db: Session, *, agency: str = "all", limit: int = 30) -> list[dict]:
    agency = (agency or "all").lower()
    alerts: list[dict] = []

    if agency in ("all", "nira"):
        alerts.extend(_identity_fraud_alerts(db))

    if agency in ("all", "kcca"):
        alerts.extend(_property_fraud_alerts(db))

    if agency in ("all", "ura"):
        pending_tax = (
            _payment_property_user_query(db)
            .filter(_payment_not_deleted(), _rent_payment_type_filter())
            .order_by(Payment.payment_date.desc())
            .limit(12)
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
                    "payment_id": pay.id,
                }
            )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(
        key=lambda a: (
            severity_rank.get(str(a.get("severity", "medium")).lower(), 2),
            a.get("created_at") or "",
        )
    )

    seen: set[str] = set()
    deduped: list[dict] = []
    for a in alerts:
        aid = a.get("id")
        if aid in seen:
            continue
        seen.add(aid)
        deduped.append(a)

    return deduped[:limit]


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
