import os, uuid
from fastapi import APIRouter, Depends, Query, status, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.dependencies import get_current_user, require_trusted_for_listings
from app.models.user import User
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, PropertyOut, PropertySummary,
    UnitCreate, UnitUpdate, UnitStatusUpdate, UnitOut,
)
from app.services import property_service
from app.services.media_storage_service import save_media
from app.config import settings
from app.utils.response import success_response, error_response

router = APIRouter(tags=["Properties & Units"])


def _summary(prop) -> PropertySummary:
    return PropertySummary.model_validate(prop)


def _detail(prop) -> PropertyOut:
    return PropertyOut.model_validate(prop)


@router.get("/properties")
def list_properties(
    search: str = Query(""),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all properties for current user with standardized response"""
    props = property_service.get_all_properties(db, current_user.id, search, include_archived)
    return success_response(data=[_summary(p) for p in props])

@router.post("/properties", status_code=status.HTTP_201_CREATED)
def create_property(
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_trusted_for_listings),
):
    """Create new property with standardized response"""
    prop = property_service.create_property(db, data, current_user.id)
    return success_response(data=_detail(prop), message="Property created successfully")

@router.get("/properties/{property_id}")
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single property with standardized response"""
    prop = property_service.get_property(db, property_id, current_user.id)
    return success_response(data=_detail(prop))

@router.patch("/properties/{property_id}")
def update_property(
    property_id: int,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update property with standardized response"""
    prop = property_service.update_property(db, property_id, data, current_user.id)
    return success_response(data=_detail(prop), message="Property updated successfully")

@router.post("/properties/{property_id}/photo")
async def upload_property_photo(
    property_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG or WebP images allowed.")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    from app.runtime import upload_root

    content = await file.read()
    photo_url = save_media(
        content=content,
        folder="properties",
        filename=filename,
        upload_dir=upload_root(),
        content_type=file.content_type,
    )
    prop = property_service.set_property_photo(db, property_id, photo_url, current_user.id)
    return success_response(data=_detail(prop), message="Property photo updated successfully")


PROPERTY_VIDEO_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
}
PROPERTY_VIDEO_MAX_BYTES = 50 * 1024 * 1024


@router.post("/properties/{property_id}/video")
async def upload_property_video(
    property_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Optional property tour video (MP4, WebM, MOV). Max 50MB."""
    content_type = (file.content_type or "").lower()
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "mp4"
    allowed_ext = {"mp4", "webm", "mov", "avi"}
    if content_type not in PROPERTY_VIDEO_TYPES and ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail="Only MP4, WebM, or MOV videos are allowed.",
        )
    content = await file.read()
    if len(content) > PROPERTY_VIDEO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Video too large (max 50MB).")
    if ext not in allowed_ext:
        ext = "mp4"
    filename = f"{uuid.uuid4().hex}.{ext}"
    from app.runtime import upload_root

    video_url = save_media(
        content=content,
        folder="properties/videos",
        filename=filename,
        upload_dir=upload_root(),
        content_type=file.content_type,
    )
    prop = property_service.set_property_video(db, property_id, video_url, current_user.id)
    return success_response(data=_detail(prop), message="Property video uploaded successfully")


@router.post("/properties/{property_id}/archive")
def archive_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = property_service.archive_property(db, property_id, current_user.id)
    return success_response(data=_summary(prop), message="Property archived successfully")

@router.post("/properties/{property_id}/restore")
def restore_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prop = property_service.restore_property(db, property_id, current_user.id)
    return success_response(data=_summary(prop), message="Property restored successfully")


def _delete_property_handler(property_id: int, db: Session, current_user: User):
    """Permanently delete a property and all its units (not reversible)."""
    property_service.delete_property(db, property_id, current_user.id)
    return success_response(message="Property deleted permanently")


@router.delete("/properties/{property_id}")
def delete_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _delete_property_handler(property_id, db, current_user)


@router.post("/properties/{property_id}/delete")
def delete_property_post(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """POST alias for hosts or proxies that block DELETE."""
    return _delete_property_handler(property_id, db, current_user)


@router.get("/properties/{property_id}/units")
def list_units(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List units for property with standardized response"""
    units = property_service.get_units_by_property(db, property_id, current_user.id)
    return success_response(data=units)

@router.post("/properties/{property_id}/units", status_code=status.HTTP_201_CREATED)
def create_unit(
    property_id: int,
    data: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create unit with standardized response"""
    unit = property_service.create_unit(db, property_id, data, current_user.id)
    return success_response(data=unit, message="Unit created successfully")

@router.patch("/units/{unit_id}")
def update_unit(
    unit_id: int,
    data: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = property_service.update_unit(db, unit_id, data, current_user.id)
    return success_response(data=unit, message="Unit updated successfully")

@router.patch("/units/{unit_id}/status")
def update_unit_status(
    unit_id: int,
    data: UnitStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = property_service.update_unit_status(db, unit_id, data, current_user.id)
    return success_response(data=unit, message="Unit status updated successfully")

@router.delete("/units/{unit_id}")
def delete_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    property_service.delete_unit(db, unit_id, current_user.id)
    return success_response(message="Unit deleted successfully")