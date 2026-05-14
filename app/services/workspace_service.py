"""Aggregated metrics for admin / staff (agent) workspace dashboards."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.property import Property
from app.models.tenant import Tenant, TenantStatus
from app.models.payment import Payment, PaymentType
from app.models.maintenance import MaintenanceRequest
from app.models.audit import AuditLog


def _role_value(role) -> str:
    return role.value if hasattr(role, "value") else str(role)


def admin_summary(db: Session) -> dict[str, Any]:
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
        monthly_platform.append(
            {
                "month": MONTHS[m - 1],
                "year": y,
                "users": int(new_users),
                "properties": int(new_props),
                "payment_volume": float(vol),
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

    return {
        "users_total": int(users_total),
        "users_by_role": users_by_role,
        "properties_total": int(properties_total),
        "properties_active": int(properties_active),
        "tenants_active": int(tenants_active),
        "payments_rent_this_month": float(payments_rent_this_month),
        "maintenance_open": int(maintenance_open),
        "maintenance_in_progress": int(maintenance_in_progress),
        "monthly_platform": monthly_platform,
        "recent_audit": recent_audit,
        "recent_users": recent_users,
    }


def staff_summary(db: Session) -> dict[str, Any]:
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

    pipeline_stages = [
        {"stage": "New leads", "count": 0},
        {"stage": "Contacted", "count": 0},
        {"stage": "Viewing", "count": 0},
        {"stage": "Negotiating", "count": 0},
        {"stage": "Closed", "count": 0},
    ]

    today = date.today()
    commission_trend = []
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        commission_trend.append({"m": MONTHS[m - 1], "v": 0.0})

    return {
        "maintenance": {
            "open": int(maintenance_open),
            "in_progress": int(maintenance_in_progress),
            "resolved": int(maintenance_resolved),
        },
        "properties_listed": int(properties_listed),
        "pipeline_stages": pipeline_stages,
        "recent_leads": [],
        "commission_trend": commission_trend,
        "kpis": {
            "total_leads": 0,
            "active_deals": int(maintenance_open) + int(maintenance_in_progress),
            "commissions_ytd_ugx": 0.0,
            "pending_payout_ugx": 0.0,
        },
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
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]
    return items, total
