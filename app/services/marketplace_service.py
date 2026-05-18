"""Public marketplace listings (vacant units on active properties)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.property import Property, Unit, UnitStatus, UnitType


def _beds_for_unit_type(ut: UnitType) -> int:
    if ut in (UnitType.studio, UnitType.bedsitter):
        return 1
    if ut == UnitType.one_bedroom:
        return 1
    if ut == UnitType.two_bedroom:
        return 2
    if ut == UnitType.three_bedroom:
        return 3
    return 1


def _serialize_unit(unit: Unit, prop: Property) -> dict[str, Any]:
    ut = unit.unit_type
    ut_val = ut.value if hasattr(ut, "value") else str(ut)
    amenities = unit.amenities if isinstance(unit.amenities, list) else []
    parking = "On request"
    if amenities:
        for a in amenities:
            if isinstance(a, str) and "park" in a.lower():
                parking = a
                break
    return {
        "id": unit.id,
        "property_id": prop.id,
        "title": f"{prop.name} · Unit {unit.unit_number}",
        "price": float(unit.rent_amount or 0),
        "loc": prop.district or prop.parish or "Uganda",
        "address": prop.address,
        "beds": _beds_for_unit_type(unit.unit_type),
        "baths": 1,
        "sqft": 0,
        "verified": bool(prop.is_active),
        "image": prop.photo_path or "/images/hero-villa.jpg",
        "desc": (unit.description or prop.description or "").strip() or f"{prop.name} — {ut_val.replace('_', ' ')}.",
        "parking": parking,
        "unit_type": ut_val,
        "floor_number": unit.floor_number or 0,
        "amenities": amenities,
    }


def list_marketplace_listings(
    db: Session,
    *,
    search: str = "",
    min_rent: Optional[float] = None,
    max_rent: Optional[float] = None,
    unit_type: Optional[str] = None,
) -> List[dict[str, Any]]:
    q = (
        db.query(Unit)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.is_active.is_(True), Unit.status == UnitStatus.vacant)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                Property.name.ilike(term),
                Property.address.ilike(term),
                Property.description.ilike(term),
                Property.parish.ilike(term),
                Property.district.ilike(term),
                Unit.unit_number.ilike(term),
                Unit.description.ilike(term),
            )
        )
    if min_rent is not None:
        q = q.filter(Unit.rent_amount >= Decimal(str(min_rent)))
    if max_rent is not None:
        q = q.filter(Unit.rent_amount <= Decimal(str(max_rent)))
    if unit_type and unit_type.strip():
        raw = unit_type.strip().lower().replace(" ", "_")
        try:
            ut_enum = UnitType(raw)
            q = q.filter(Unit.unit_type == ut_enum)
        except ValueError:
            pass

    units = q.options(joinedload(Unit.parent_property)).order_by(Unit.rent_amount.asc()).all()
    out: List[dict[str, Any]] = []
    for u in units:
        prop = u.parent_property
        if not prop:
            continue
        out.append(_serialize_unit(u, prop))
    return out


def get_marketplace_listing(db: Session, unit_id: int) -> Optional[dict[str, Any]]:
    unit = (
        db.query(Unit)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Unit.id == unit_id,
            Property.is_active.is_(True),
            Unit.status == UnitStatus.vacant,
        )
        .options(joinedload(Unit.parent_property))
        .first()
    )
    if not unit or not unit.parent_property:
        return None
    return _serialize_unit(unit, unit.parent_property)


def get_unit_card(db: Session, unit_id: int) -> Optional[dict[str, Any]]:
    """Serialize a unit for saved list (any status; property must be active)."""
    unit = (
        db.query(Unit)
        .options(joinedload(Unit.parent_property))
        .filter(Unit.id == unit_id)
        .first()
    )
    if not unit or not unit.parent_property or not unit.parent_property.is_active:
        return None
    return _serialize_unit(unit, unit.parent_property)
