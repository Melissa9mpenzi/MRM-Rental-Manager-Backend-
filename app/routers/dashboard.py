from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from datetime import date

from app.database import get_db
from app.dependencies import require_landlord
from app.models.user import User
from app.models.property import Property, Unit, UnitStatus
from app.models.tenant import Tenant, TenantStatus
from app.models.payment import Payment, PaymentType
from app.services.arrears_service import get_arrears_list
from app.utils.response import success_response

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_landlord),
):
    uid = current_user.id
    today = date.today()

    # Properties & units
    properties = db.query(Property).options(joinedload(Property.units)).filter(
        Property.owner_id == uid, Property.is_active == True
    ).all()

    total_properties  = len(properties)
    property_ids      = [p.id for p in properties]
    all_units         = [u for p in properties for u in p.units]
    total_units       = len(all_units)
    occupied_units    = sum(1 for u in all_units if u.status == UnitStatus.occupied)
    vacant_units      = sum(1 for u in all_units if u.status == UnitStatus.vacant)
    maintenance_units = sum(1 for u in all_units if u.status == UnitStatus.maintenance)
    occupancy_rate    = round(occupied_units / total_units * 100, 1) if total_units else 0.0

    # Payments — current month
    payments = db.query(Payment).filter(
        Payment.owner_id == uid,
        Payment.is_deleted == False,
        Payment.payment_type == PaymentType.rent,
    ).all()

    this_month_collected = sum(
        float(p.amount) for p in payments
        if p.period_month == today.month and p.period_year == today.year
    )

    # Monthly income for last 6 months (bar chart data)
    monthly_income = []
    MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        if m <= 0:
            m += 12; y -= 1
        collected = sum(
            float(p.amount) for p in payments
            if p.period_month == m and p.period_year == y
        )
        monthly_income.append({"month": MONTHS[m-1], "year": y, "collected": collected})

    # Arrears
    arrears_list = get_arrears_list(db, uid)
    total_arrears = sum(a["balance_due"] for a in arrears_list if a["balance_due"] > 0)
    tenants_in_arrears = sum(1 for a in arrears_list if a["balance_due"] > 0)

    # Active tenants
    total_tenants = db.query(Tenant).filter(
        Tenant.owner_id == uid, Tenant.status == TenantStatus.active
    ).count()

    # Expected monthly rent (all occupied units)
    expected_monthly_rent = sum(
        float(u.rent_amount) for u in all_units if u.status == UnitStatus.occupied
    )

    # Recent properties
    recent = sorted(properties, key=lambda p: p.created_at or date.min, reverse=True)[:3]
    recent_properties = [
        {
            "id":             p.id,
            "name":           p.name,
            "address":        p.address,
            "photo_path":     p.photo_path,
            "total_units":    len(p.units),
            "occupied_units": sum(1 for u in p.units if u.status == UnitStatus.occupied),
            "occupancy_rate": round(sum(1 for u in p.units if u.status == UnitStatus.occupied) / len(p.units) * 100, 1) if p.units else 0.0,
        }
        for p in recent
    ]

    # Top arrears (max 5)
    top_arrears = [a for a in arrears_list if a["balance_due"] > 0][:5]

    collection_rate = (
        round(this_month_collected / expected_monthly_rent * 100, 1)
        if expected_monthly_rent > 0
        else 0.0
    )

    active_tenant_rows = (
        db.query(Tenant)
        .filter(Tenant.owner_id == uid, Tenant.status == TenantStatus.active)
        .all()
    )
    if active_tenant_rows:
        avg_days = sum((today - t.lease_start).days for t in active_tenant_rows if t.lease_start) / len(
            active_tenant_rows
        )
        avg_tenancy_months = round(avg_days / 30.44, 1)
    else:
        avg_tenancy_months = 0.0

    occupancy_by_property = [
        {
            "id": p.id,
            "name": p.name,
            "total_units": len(p.units),
            "occupied_units": sum(1 for u in p.units if u.status == UnitStatus.occupied),
            "vacant_units": sum(1 for u in p.units if u.status == UnitStatus.vacant),
            "occupancy_rate": round(
                sum(1 for u in p.units if u.status == UnitStatus.occupied) / len(p.units) * 100, 1
            )
            if p.units
            else 0.0,
        }
        for p in properties
    ]

    return success_response(
        data={
        "total_properties":       total_properties,
        "total_units":            total_units,
        "total_tenants":          total_tenants,
        "occupied_units":         occupied_units,
        "vacant_units":           vacant_units,
        "maintenance_units":      maintenance_units,
        "occupancy_rate":         occupancy_rate,
        "expected_monthly_rent":  expected_monthly_rent,
        "this_month_collected":   this_month_collected,
        "total_arrears":          total_arrears,
        "tenants_in_arrears":     tenants_in_arrears,
        "monthly_income":         monthly_income,
        "recent_properties":      recent_properties,
        "top_arrears":            top_arrears,
        "collection_rate":        collection_rate,
        "avg_tenancy_months":     avg_tenancy_months,
        "occupancy_by_property":  occupancy_by_property,
        }
    )