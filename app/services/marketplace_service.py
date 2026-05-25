"""Public marketplace listings (vacant units on active properties)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session, joinedload

from app.models.property import Property, Unit, UnitStatus, UnitType
from app.models.user import User
from app.services.compliance_service import compliance_badges_public, listing_compliance_badges


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


def _serialize_unit(
    unit: Unit,
    prop: Property,
    *,
    badges: dict[str, bool] | None = None,
) -> dict[str, Any]:
    ut = unit.unit_type
    ut_val = ut.value if hasattr(ut, "value") else str(ut)
    amenities = unit.amenities if isinstance(unit.amenities, list) else []
    parking = "On request"
    for a in amenities:
        if isinstance(a, str) and "park" in a.lower():
            parking = a
            break
    beds = unit.bedrooms if unit.bedrooms is not None else _beds_for_unit_type(unit.unit_type)
    baths = unit.bathrooms if unit.bathrooms is not None else 1
    area = float(unit.area_sqm or 0)
    return {
        "id": unit.id,
        "property_id": prop.id,
        "title": f"{prop.name} · Unit {unit.unit_number}",
        "price": float(unit.rent_amount or 0),
        "loc": prop.district or prop.parish or "Uganda",
        "address": prop.address,
        "beds": beds,
        "baths": baths,
        "sqft": area,
        "area_sqm": area,
        "verified": bool(badges and badges.get("marketplace_live")),
        "compliance": compliance_badges_public(badges or {}),
        "image": prop.photo_path or "/images/hero-villa.jpg",
        "desc": (unit.description or prop.description or "").strip() or f"{prop.name} — {ut_val.replace('_', ' ')}.",
        "parking": parking,
        "unit_type": ut_val,
        "listing_category": unit.listing_category,
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
    listing_category: Optional[str] = None,
    min_bedrooms: Optional[int] = None,
    amenities: Optional[List[str]] = None,
) -> List[dict[str, Any]]:
    q = (
        db.query(Unit)
        .join(Property, Unit.property_id == Property.id)
        .join(User, Property.owner_id == User.id)
        .filter(
            Property.is_active.is_(True),
            Property.gov_verification_status == "verified",
            User.kyc_review_status == "approved",
            User.is_active.is_(True),
            User.gov_suspended.is_(False),
            Unit.status == UnitStatus.vacant,
        )
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
                Unit.listing_category.ilike(term),
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
    if listing_category and listing_category.strip():
        q = q.filter(Unit.listing_category == listing_category.strip())
    if min_bedrooms is not None and min_bedrooms > 0:
        q = q.filter(Unit.bedrooms >= min_bedrooms)

    units = q.options(joinedload(Unit.parent_property)).order_by(Unit.rent_amount.asc()).all()
    out: List[dict[str, Any]] = []
    want_amenities = [a.strip() for a in (amenities or []) if a and a.strip()]

    for u in units:
        prop = u.parent_property
        if not prop:
            continue
        owner = prop.owner if prop.owner else db.get(User, prop.owner_id)
        badge_row = listing_compliance_badges(db, owner=owner, prop=prop)
        row = _serialize_unit(u, prop, badges=badge_row)
        if want_amenities:
            am_list = row.get("amenities") or []
            am_blob = " ".join(str(x) for x in am_list).lower()
            ok = True
            for aid in want_amenities:
                key = aid.lower()
                if aid in am_list:
                    continue
                if key == "wifi" and not any(x in am_blob for x in ("wifi", "fibre", "fiber", "internet")):
                    ok = False
                    break
                if key == "parking" and "park" not in am_blob:
                    ok = False
                    break
                if key == "security" and not any(x in am_blob for x in ("security", "gated", "cctv")):
                    ok = False
                    break
                if key == "balcony" and "balcony" not in am_blob and "terrace" not in am_blob:
                    ok = False
                    break
                if key == "generator" and "generator" not in am_blob and "backup" not in am_blob:
                    ok = False
                    break
                if key == "furnished" and "furnish" not in am_blob:
                    ok = False
                    break
            if not ok:
                continue
        out.append(row)
    return out


def get_marketplace_listing(db: Session, unit_id: int) -> Optional[dict[str, Any]]:
    unit = (
        db.query(Unit)
        .join(Property, Unit.property_id == Property.id)
        .join(User, Property.owner_id == User.id)
        .filter(
            Unit.id == unit_id,
            Property.is_active.is_(True),
            Property.gov_verification_status == "verified",
            User.kyc_review_status == "approved",
            User.gov_suspended.is_(False),
            Unit.status == UnitStatus.vacant,
        )
        .options(joinedload(Unit.parent_property))
        .first()
    )
    if not unit or not unit.parent_property:
        return None
    prop = unit.parent_property
    owner = prop.owner if prop.owner else db.get(User, prop.owner_id)
    badges = listing_compliance_badges(db, owner=owner, prop=prop)
    return _serialize_unit(unit, prop, badges=badges)


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
    prop = unit.parent_property
    owner = prop.owner if prop.owner else db.get(User, prop.owner_id)
    badges = listing_compliance_badges(db, owner=owner, prop=prop)
    return _serialize_unit(unit, prop, badges=badges)
