"""Live database counts — no seeded or hardcoded dashboard figures."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.lease import Lease, LeaseStatus
from app.models.payment import Payment
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.user import User, UserRole


def live_data_summary(db: Session) -> dict[str, Any]:
    """Counts from real tables only (registrations, listings, leases, payments)."""
    users_by_role = (
        db.query(User.role, func.count(User.id))
        .group_by(User.role)
        .all()
    )
    role_counts = {
        (r.value if hasattr(r, "value") else str(r)): int(c or 0)
        for r, c in users_by_role
    }

    return {
        "data_source": "database",
        "demo_seed_blocked_in_production": True,
        "users_total": int(db.query(func.count(User.id)).scalar() or 0),
        "users_by_role": role_counts,
        "properties": int(db.query(func.count(Property.id)).scalar() or 0),
        "units": int(db.query(func.count(Unit.id)).scalar() or 0),
        "tenants": int(db.query(func.count(Tenant.id)).scalar() or 0),
        "leases_total": int(db.query(func.count(Lease.id)).scalar() or 0),
        "leases_active": int(
            db.query(func.count(Lease.id))
            .filter(Lease.status.in_([LeaseStatus.active, LeaseStatus.pending]))
            .scalar()
            or 0
        ),
        "payments_total": int(db.query(func.count(Payment.id)).scalar() or 0),
        "kyc_pending": int(
            db.query(func.count(User.id))
            .filter(
                User.role.in_([UserRole.landlord, UserRole.staff, UserRole.tenant]),
                User.kyc_review_status == "pending",
            )
            .scalar()
            or 0
        ),
        "has_rental_operations": bool(
            (db.query(func.count(Tenant.id)).scalar() or 0) > 0
            or (db.query(func.count(Lease.id)).scalar() or 0) > 0
            or (db.query(func.count(Payment.id)).scalar() or 0) > 0
        ),
    }
