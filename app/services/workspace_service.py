"""Aggregated metrics for admin / staff (agent) workspace dashboards."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.user import User, UserRole
from app.models.property import Property, UnitStatus
from app.models.tenant import Tenant, TenantStatus
from app.models.payment import Payment, PaymentType
from app.models.maintenance import MaintenanceRequest
from app.models.audit import AuditLog
from app.models.lease import Lease


def _role_value(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


# Approximate positions on the simplified Uganda map (viewBox 0–100).
_DISTRICT_COORDS: dict[str, tuple[int, int]] = {
    "kampala": (52, 42),
    "wakiso": (48, 48),
    "entebbe": (44, 52),
    "mukono": (58, 55),
    "jinja": (66, 50),
    "mbale": (72, 36),
    "gulu": (44, 20),
    "lira": (50, 26),
    "mbarara": (36, 64),
    "arua": (26, 18),
    "masaka": (42, 58),
    "fort portal": (32, 38),
    "soroti": (62, 32),
    "kasese": (30, 48),
    "hoima": (40, 44),
}


def _district_key(name: Optional[str]) -> str:
    return (name or "kampala").strip().lower()


def platform_live_activity(db: Session) -> dict[str, Any]:
    """Real-time platform activity for the super-admin live map panel."""
    now = datetime.utcnow()
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    thirty_min_ago = now - timedelta(minutes=30)

    online_now = (
        db.query(func.count(User.id))
        .filter(
            User.is_active == True,
            or_(
                User.refresh_token.isnot(None),
                User.last_login >= thirty_min_ago,
            ),
        )
        .scalar()
        or 0
    )

    new_signups_today = (
        db.query(func.count(User.id))
        .filter(User.created_at >= today_start)
        .scalar()
        or 0
    )

    payments_today_ugx = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.is_deleted == False, Payment.payment_date == today)
        .scalar()
    )
    if payments_today_ugx is None:
        payments_today_ugx = Decimal("0")

    transactions_today = (
        db.query(func.count(Payment.id))
        .filter(Payment.is_deleted == False, Payment.payment_date == today)
        .scalar()
        or 0
    )

    maintenance_open = (
        db.query(func.count(MaintenanceRequest.id))
        .filter(MaintenanceRequest.status == "open")
        .scalar()
        or 0
    )
    maintenance_in_progress = (
        db.query(func.count(MaintenanceRequest.id))
        .filter(MaintenanceRequest.status == "in_progress")
        .scalar()
        or 0
    )
    pending_kyc = (
        db.query(func.count(User.id))
        .filter(User.kyc_review_status == "pending")
        .scalar()
        or 0
    )
    system_alerts = int(maintenance_open) + int(maintenance_in_progress) + int(pending_kyc)

    district_rows = (
        db.query(Property.district, func.count(Property.id))
        .filter(Property.is_active == True)
        .group_by(Property.district)
        .order_by(func.count(Property.id).desc())
        .limit(14)
        .all()
    )

    map_nodes: list[dict[str, Any]] = []
    for district_name, count in district_rows:
        key = _district_key(district_name)
        x, y = _DISTRICT_COORDS.get(key, (50, 45))
        c = int(count)
        map_nodes.append(
            {
                "district": district_name or "Kampala",
                "count": c,
                "x": x,
                "y": y,
                "size": min(16, max(7, 6 + c)),
                "intensity": min(1.0, 0.35 + c * 0.08),
            }
        )

    return {
        "online_now": int(online_now),
        "new_signups_today": int(new_signups_today),
        "payments_today_ugx": float(payments_today_ugx),
        "transactions_today": int(transactions_today),
        "system_alerts": system_alerts,
        "map_nodes": map_nodes,
        "updated_at": now.isoformat(),
    }


def admin_summary(db: Session) -> dict[str, Any]:
    from app.services.platform_data_service import live_data_summary

    live = live_data_summary(db)
    users_total = db.query(func.count(User.id)).scalar() or 0

    by_role_rows = db.query(User.role, func.count(User.id)).group_by(User.role).all()
    users_by_role: dict[str, int] = {}
    for r, c in by_role_rows:
        users_by_role[_role_value(r)] = int(c)

    properties_total = db.query(func.count(Property.id)).scalar() or 0
    properties_active = (
        db.query(func.count(Property.id)).filter(Property.is_active == True).scalar() or 0
    )

    tenants_active = (
        db.query(func.count(Tenant.id)).filter(Tenant.status == TenantStatus.active).scalar() or 0
    )

    today = date.today()
    payments_rent_this_month = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.is_deleted == False,
            Payment.payment_type == PaymentType.rent,
            Payment.period_month == today.month,
            Payment.period_year == today.year,
        )
        .scalar()
    )
    if payments_rent_this_month is None:
        payments_rent_this_month = Decimal("0")

    maintenance_open = (
        db.query(func.count(MaintenanceRequest.id)).filter(MaintenanceRequest.status == "open").scalar()
        or 0
    )
    maintenance_in_progress = (
        db.query(func.count(MaintenanceRequest.id))
        .filter(MaintenanceRequest.status == "in_progress")
        .scalar()
        or 0
    )

    monthly_platform = []
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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
        new_users = (
            db.query(func.count(User.id))
            .filter(User.created_at >= start_dt, User.created_at < end_dt)
            .scalar()
            or 0
        )
        new_props = (
            db.query(func.count(Property.id))
            .filter(Property.created_at >= start_dt, Property.created_at < end_dt)
            .scalar()
            or 0
        )
        vol = (
            db.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(
                Payment.is_deleted == False,
                Payment.payment_type == PaymentType.rent,
                Payment.period_month == int(m),
                Payment.period_year == int(y),
            )
            .scalar()
        )
        if vol is None:
            vol = Decimal("0")
        new_leases = (
            db.query(func.count(Lease.id))
            .filter(Lease.created_at >= start_dt, Lease.created_at < end_dt)
            .scalar()
            or 0
        )
        monthly_platform.append(
            {
                "month": MONTHS[m - 1],
                "year": y,
                "users": int(new_users),
                "properties": int(new_props),
                "payment_volume": float(vol),
                "leases": int(new_leases),
            }
        )

    recent_audit = []
    for row in (
        db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(8).all()
    ):
        recent_audit.append(
            {
                "id": row.id,
                "action": row.action,
                "table_name": row.table_name,
                "record_id": row.record_id,
                "user_id": row.user_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    recent_users = []
    for u in db.query(User).order_by(User.created_at.desc()).limit(8).all():
        recent_users.append(
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": _role_value(u.role),
                "is_active": u.is_active,
                "email_verified": u.email_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
        )

    rev_rows = (
        db.query(Payment.payment_type, func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.is_deleted == False,
            Payment.period_month == today.month,
            Payment.period_year == today.year,
        )
        .group_by(Payment.payment_type)
        .all()
    )
    rev_total = sum(float(amt or 0) for _, amt in rev_rows)
    rev_colors = {
        PaymentType.rent.value: "#00C896",
        PaymentType.deposit.value: "#3B82F6",
        PaymentType.penalty.value: "#A78BFA",
        PaymentType.other.value: "#F59E0B",
    }
    rev_labels = {
        PaymentType.rent.value: "Rent Payments",
        PaymentType.deposit.value: "Deposits",
        PaymentType.penalty.value: "Penalties",
        PaymentType.other.value: "Other",
    }
    revenue_breakdown: list[dict[str, Any]] = []
    if rev_total > 0:
        for ptype, amt in rev_rows:
            key = ptype.value if hasattr(ptype, "value") else str(ptype)
            pct = max(1, round(100 * float(amt or 0) / rev_total))
            revenue_breakdown.append(
                {
                    "name": rev_labels.get(key, key.title()),
                    "value": pct,
                    "color": rev_colors.get(key, "#64748b"),
                    "amount_ugx": float(amt or 0),
                }
            )

    return {
        "data_source": "database",
        "live_data": live,
        "users_total": int(users_total),
        "users_by_role": users_by_role,
        "properties_total": int(properties_total),
        "properties_active": int(properties_active),
        "tenants_active": int(tenants_active),
        "payments_rent_this_month": float(payments_rent_this_month),
        "maintenance_open": int(maintenance_open),
        "maintenance_in_progress": int(maintenance_in_progress),
        "monthly_platform": monthly_platform,
        "revenue_breakdown": revenue_breakdown,
        "recent_audit": recent_audit,
        "recent_users": recent_users,
        "platform_live": platform_live_activity(db),
    }


def staff_summary(db: Session, owner_id: int | None = None) -> dict[str, Any]:
    from app.services import agent_crm_service

    maintenance_open = (
        db.query(func.count(MaintenanceRequest.id)).filter(MaintenanceRequest.status == "open").scalar()
        or 0
    )
    maintenance_in_progress = (
        db.query(func.count(MaintenanceRequest.id))
        .filter(MaintenanceRequest.status == "in_progress")
        .scalar()
        or 0
    )
    maintenance_resolved = (
        db.query(func.count(MaintenanceRequest.id)).filter(MaintenanceRequest.status == "resolved").scalar()
        or 0
    )

    properties_listed = db.query(func.count(Property.id)).filter(Property.is_active == True).scalar() or 0

    if owner_id:
        pipeline_stages = agent_crm_service.pipeline_counts(db, owner_id)
        recent_leads = agent_crm_service.recent_leads_for_dashboard(db, owner_id)
        commission_trend = agent_crm_service.commission_trend(db, owner_id)
        kpis = agent_crm_service.staff_kpis(db, owner_id)
    else:
        pipeline_stages = [
            {"stage": "New leads", "count": 0},
            {"stage": "Contacted", "count": 0},
            {"stage": "Viewing", "count": 0},
            {"stage": "Negotiating", "count": 0},
            {"stage": "Closed", "count": 0},
        ]
        recent_leads = []
        today = date.today()
        MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        commission_trend = []
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            commission_trend.append({"m": MONTHS[m - 1], "v": 0.0})
        kpis = {
            "total_leads": 0,
            "active_deals": int(maintenance_open) + int(maintenance_in_progress),
            "commissions_ytd_ugx": 0.0,
            "pending_payout_ugx": 0.0,
        }

    return {
        "maintenance": {
            "open": int(maintenance_open),
            "in_progress": int(maintenance_in_progress),
            "resolved": int(maintenance_resolved),
        },
        "properties_listed": int(properties_listed),
        "pipeline_stages": pipeline_stages,
        "recent_leads": recent_leads,
        "commission_trend": commission_trend,
        "kpis": kpis,
    }


def admin_list_users(
    db: Session,
    *,
    search: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    q = db.query(User)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((User.email.ilike(like)) | (User.full_name.ilike(like)))
    if role:
        try:
            q = q.filter(User.role == UserRole(role.strip().lower()))
        except ValueError:
            pass
    total = q.count()
    rows = q.order_by(User.id.desc()).offset(offset).limit(limit).all()
    items = [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "phone": u.phone,
            "role": _role_value(u.role),
            "is_active": u.is_active,
            "email_verified": u.email_verified,
            "kyc_submitted_at": u.kyc_submitted_at.isoformat() if u.kyc_submitted_at else None,
            "kyc_review_status": getattr(u, "kyc_review_status", "none") or "none",
            "trusted_for_commerce": bool(getattr(u, "trusted_for_commerce", True)),
            "gov_suspended": bool(getattr(u, "gov_suspended", False)),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]
    return items, total


def admin_user_account_action(
    db: Session,
    *,
    actor_id: int,
    target_user_id: int,
    action: str,
) -> dict[str, Any]:
    """
    System admin account controls: disconnect (deactivate + revoke sessions) or reconnect.
    """
    from app.services.audit_service import log_action

    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    act = (action or "").strip().lower()
    if act not in ("disconnect", "reconnect"):
        raise HTTPException(status_code=400, detail="action must be disconnect or reconnect.")

    if target_user_id == actor_id:
        raise HTTPException(status_code=400, detail="You cannot disconnect or reconnect your own account.")

    role = _role_value(user.role)
    if role == UserRole.system_admin.value:
        active_admins = (
            db.query(func.count(User.id))
            .filter(User.role == UserRole.system_admin, User.is_active == True)  # noqa: E712
            .scalar()
            or 0
        )
        if act == "disconnect" and active_admins <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot disconnect the last active system administrator.",
            )

    was_active = bool(user.is_active)
    if act == "disconnect":
        if not was_active:
            return {
                "id": user.id,
                "is_active": False,
                "message": "Account is already disconnected.",
            }
        user.is_active = False
        user.refresh_token = None
        user.trusted_for_commerce = False
        message = f"Disconnected {user.email} — they can no longer sign in."
        audit_action = "admin_disconnect_user"
    else:
        if was_active:
            return {
                "id": user.id,
                "is_active": True,
                "message": "Account is already active.",
            }
        user.is_active = True
        user.gov_suspended = False
        user.gov_suspension_reason = None
        user.gov_suspended_at = None
        message = f"Reconnected {user.email} — they can sign in again."
        audit_action = "admin_reconnect_user"

    db.commit()
    db.refresh(user)

    log_action(
        db,
        user_id=actor_id,
        action=audit_action,
        table_name="users",
        record_id=user.id,
        old_value={"is_active": was_active},
        new_value={"is_active": user.is_active, "email": user.email, "role": role},
    )

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": role,
        "is_active": user.is_active,
        "message": message,
    }


def admin_list_properties(
    db: Session,
    *,
    search: Optional[str] = None,
    district: Optional[str] = None,
    active_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Platform-wide property directory for system administrator."""
    q = db.query(Property).options(joinedload(Property.units), joinedload(Property.owner))
    if active_only:
        q = q.filter(Property.is_active == True)
    if district:
        q = q.filter(Property.district.ilike(f"%{district.strip()}%"))
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            (Property.name.ilike(like))
            | (Property.address.ilike(like))
            | (Property.parish.ilike(like))
        )
    total = q.count()
    rows = q.order_by(Property.created_at.desc()).offset(offset).limit(limit).all()
    items: list[dict[str, Any]] = []
    for p in rows:
        units = list(p.units or [])
        occupied = sum(1 for u in units if u.status == UnitStatus.occupied)
        vacant = sum(1 for u in units if u.status == UnitStatus.vacant)
        vacant_units_list = [u for u in units if u.status == UnitStatus.vacant]
        listing_unit_id = (
            vacant_units_list[0].id
            if vacant_units_list
            else (units[0].id if units else None)
        )
        owner = p.owner
        items.append(
            {
                "id": p.id,
                "listing_unit_id": listing_unit_id,
                "name": p.name,
                "address": p.address,
                "parish": p.parish,
                "district": p.district or "Kampala",
                "is_active": bool(p.is_active),
                "gov_verification_status": getattr(p, "gov_verification_status", None) or "pending",
                "photo_path": p.photo_path,
                "owner_id": p.owner_id,
                "owner_name": owner.full_name if owner else None,
                "owner_email": owner.email if owner else None,
                "total_units": len(units),
                "occupied_units": occupied,
                "vacant_units": vacant,
                "occupancy_rate": round((occupied / len(units)) * 100, 1) if units else 0.0,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )
    return items, total
