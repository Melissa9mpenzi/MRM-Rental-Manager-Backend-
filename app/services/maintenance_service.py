"""
Maintenance Request Service
Handles CRUD for maintenance requests scoped to the owning landlord.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.models.maintenance import MaintenanceRequest
from app.models.property import Unit, Property


VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}


def _unit_belongs_to_owner(db: Session, unit_id: int, owner_id: int) -> Unit:
    unit = (
        db.query(Unit)
        .join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.owner_id == owner_id)
        .first()
    )
    if not unit:
        raise HTTPException(404, "Unit not found or not yours.")
    return unit


def _enrich(req: MaintenanceRequest) -> dict:
    unit = req.unit if hasattr(req, "unit") and req.unit else None
    prop = unit.parent_property if unit and hasattr(unit, "parent_property") else None
    return {
        "id": req.id,
        "unit_id": req.unit_id,
        "unit_number": unit.unit_number if unit else None,
        "property_name": prop.name if prop else None,
        "property_id": prop.id if prop else None,
        "reported_by": req.reported_by,
        "title": req.title,
        "description": req.description,
        "priority": req.priority,
        "status": req.status,
        "cost_incurred": req.cost_incurred,
        "resolution_note": req.resolution_note,
        "photo_path": req.photo_path,
        "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
    }


def _load(db: Session, request_id: int, owner_id: int) -> MaintenanceRequest:
    req = (
        db.query(MaintenanceRequest)
        .options(joinedload(MaintenanceRequest.unit).joinedload(Unit.parent_property))
        .join(Unit, MaintenanceRequest.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(MaintenanceRequest.id == request_id, Property.owner_id == owner_id)
        .first()
    )
    if not req:
        raise HTTPException(404, "Maintenance request not found.")
    return req


def list_requests(
    db: Session,
    owner_id: int,
    status: Optional[str] = None,
    unit_id: Optional[int] = None,
    property_id: Optional[int] = None,
) -> list:
    q = (
        db.query(MaintenanceRequest)
        .options(joinedload(MaintenanceRequest.unit).joinedload(Unit.parent_property))
        .join(Unit, MaintenanceRequest.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.owner_id == owner_id)
    )
    if status:
        q = q.filter(MaintenanceRequest.status == status)
    if unit_id:
        q = q.filter(MaintenanceRequest.unit_id == unit_id)
    if property_id:
        q = q.filter(Property.id == property_id)
    rows = q.order_by(MaintenanceRequest.created_at.desc()).all()
    return [_enrich(r) for r in rows]


def get_request(db: Session, request_id: int, owner_id: int) -> dict:
    return _enrich(_load(db, request_id, owner_id))


def create_request(
    db: Session,
    owner_id: int,
    unit_id: int,
    title: str,
    description: Optional[str],
    priority: str,
    upload_dir: str,
    photo: Optional[UploadFile] = None,
    reported_by: Optional[int] = None,
) -> dict:
    _unit_belongs_to_owner(db, unit_id, owner_id)

    if priority not in VALID_PRIORITIES:
        priority = "medium"

    photo_path = None
    if photo and photo.filename:
        dest_dir = os.path.join(upload_dir, "maintenance")
        os.makedirs(dest_dir, exist_ok=True)
        ext = os.path.splitext(photo.filename)[1].lower() or ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(dest_dir, fname), "wb") as f:
            shutil.copyfileobj(photo.file, f)
        photo_path = f"/uploads/maintenance/{fname}"

    req = MaintenanceRequest(
        unit_id=unit_id,
        reported_by=reported_by if reported_by else owner_id,
        title=title,
        description=description,
        priority=priority,
        status="open",
        photo_path=photo_path,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return get_request(db, req.id, owner_id)


def update_request(
    db: Session,
    request_id: int,
    owner_id: int,
    status: Optional[str] = None,
    resolution_note: Optional[str] = None,
    cost_incurred: Optional[str] = None,
    priority: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    req = _load(db, request_id, owner_id)

    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(400, f"Invalid status. Use one of: {VALID_STATUSES}")
        req.status = status
        if status == "resolved" and not req.resolved_at:
            req.resolved_at = datetime.utcnow()

    if resolution_note is not None:
        req.resolution_note = resolution_note
    if cost_incurred is not None:
        req.cost_incurred = cost_incurred
    if priority and priority in VALID_PRIORITIES:
        req.priority = priority
    if title is not None:
        req.title = title
    if description is not None:
        req.description = description

    req.updated_at = datetime.utcnow()
    db.commit()
    return get_request(db, request_id, owner_id)


def delete_request(db: Session, request_id: int, owner_id: int) -> None:
    req = _load(db, request_id, owner_id)
    db.delete(req)
    db.commit()
