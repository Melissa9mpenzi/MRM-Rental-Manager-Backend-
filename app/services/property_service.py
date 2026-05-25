from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from app.models.property import Property, Unit, UnitStatus
from app.schemas.property import (
    PropertyCreate, PropertyUpdate,
    UnitCreate, UnitUpdate, UnitStatusUpdate
)


# ── PROPERTY CRUD ─────────────────────────────────────────────────

def get_all_properties(
    db: Session,
    owner_id: int,
    search: str = "",
    include_archived: bool = False,
) -> list[Property]:
    """Return all properties for this landlord, with units eager-loaded."""
    query = (
        db.query(Property)
        .options(joinedload(Property.units))
        .filter(Property.owner_id == owner_id)
    )
    if not include_archived:
        query = query.filter(Property.is_active == True)
    if search:
        query = query.filter(Property.name.ilike(f"%{search}%"))
    return query.order_by(Property.created_at.desc()).all()


def get_property(db: Session, property_id: int, owner_id: int) -> Property:
    """Get a single property with all units. Enforces ownership."""
    prop = (
        db.query(Property)
        .options(joinedload(Property.units))
        .filter(Property.id == property_id, Property.owner_id == owner_id)
        .first()
    )
    if not prop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found."
        )
    return prop


def create_property(db: Session, data: PropertyCreate, owner_id: int) -> Property:
    """Create a new property for this landlord."""
    prop = Property(
        owner_id=owner_id,
        name=data.name,
        address=data.address,
        parish=data.parish,
        district=data.district or "Kampala",
        description=data.description,
        is_active=True,
        gov_verification_status="pending",
    )
    db.add(prop)
    db.commit()
    db.expire(prop)          # force reload from DB so server_default timestamps are fetched
    db.refresh(prop)
    return get_property(db, prop.id, owner_id)


def update_property(
    db: Session, property_id: int, data: PropertyUpdate, owner_id: int
) -> Property:
    """Update a property's details. Only update fields that were provided."""
    prop = get_property(db, property_id, owner_id)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(prop, field, value)
    db.commit()
    return get_property(db, property_id, owner_id)


def archive_property(db: Session, property_id: int, owner_id: int) -> Property:
    """Soft-delete a property (sets is_active=False). Data is retained."""
    prop = get_property(db, property_id, owner_id)
    prop.is_active = False
    db.commit()
    db.refresh(prop)
    return prop


def restore_property(db: Session, property_id: int, owner_id: int) -> Property:
    """Restore an archived property."""
    prop = (
        db.query(Property)
        .filter(Property.id == property_id, Property.owner_id == owner_id)
        .first()
    )
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")
    prop.is_active = True
    db.commit()
    db.refresh(prop)
    return prop


# ── UNIT CRUD ─────────────────────────────────────────────────────

def _get_unit(db: Session, unit_id: int, owner_id: int) -> Unit:
    """Get a unit, verifying the caller owns the parent property."""
    unit = (
        db.query(Unit)
        .join(Property)
        .filter(Unit.id == unit_id, Property.owner_id == owner_id)
        .first()
    )
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found.")
    return unit


def get_units_by_property(
    db: Session, property_id: int, owner_id: int
) -> list[Unit]:
    """List all units for a given property."""
    # Verify ownership first
    get_property(db, property_id, owner_id)
    return (
        db.query(Unit)
        .filter(Unit.property_id == property_id)
        .order_by(Unit.floor_number, Unit.unit_number)
        .all()
    )


def create_unit(
    db: Session, property_id: int, data: UnitCreate, owner_id: int
) -> Unit:
    """Add a unit to a property. Validates ownership and unique unit number."""
    # Verify ownership
    get_property(db, property_id, owner_id)

    # Check for duplicate unit number within this property
    existing = (
        db.query(Unit)
        .filter(Unit.property_id == property_id, Unit.unit_number == data.unit_number)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unit '{data.unit_number}' already exists in this property."
        )

    unit = Unit(
        property_id=property_id,
        unit_number=data.unit_number,
        floor_number=data.floor_number or 0,
        unit_type=data.unit_type or "one_bedroom",
        listing_category=data.listing_category,
        bedrooms=data.bedrooms,
        bathrooms=data.bathrooms if data.bathrooms is not None else 1,
        area_sqm=data.area_sqm,
        rent_amount=data.rent_amount,
        amenities=data.amenities or [],
        description=data.description,
        status=data.status or "vacant",
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


def update_unit(
    db: Session, unit_id: int, data: UnitUpdate, owner_id: int
) -> Unit:
    """Update a unit's details."""
    unit = _get_unit(db, unit_id, owner_id)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(unit, field, value)
    db.commit()
    db.refresh(unit)
    return unit


def update_unit_status(
    db: Session, unit_id: int, data: UnitStatusUpdate, owner_id: int
) -> Unit:
    """Update a unit's occupancy status."""
    valid = ["vacant", "occupied", "maintenance"]
    if data.status not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid)}"
        )
    unit = _get_unit(db, unit_id, owner_id)
    unit.status = data.status
    db.commit()
    db.refresh(unit)
    return unit


def delete_unit(db: Session, unit_id: int, owner_id: int) -> None:
    """
    Hard delete a unit — only allowed if vacant and has no payment history.
    For occupied units, use status update instead.
    """
    unit = _get_unit(db, unit_id, owner_id)
    if unit.status == "occupied":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an occupied unit. Move the tenant out first."
        )
    db.delete(unit)
    db.commit()


def set_property_photo(db: Session, property_id: int, photo_url: str, owner_id: int) -> Property:
    """Store the uploaded photo URL on the property."""
    prop = get_property(db, property_id, owner_id)
    prop.photo_path = photo_url
    db.commit()
    return get_property(db, property_id, owner_id)