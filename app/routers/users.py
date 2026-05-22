"""
Users Router — profile management for the authenticated user.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.schemas.auth import UserOut
from app.config import settings
from app.utils.kyc_media import (
    content_type_allowed,
    kyc_documents_complete,
    kyc_user_dir,
    normalize_kyc_image_jpeg,
)

router = APIRouter(prefix="/users", tags=["Users"])


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None


_SELF_SERVICE_ROLES = frozenset({UserRole.tenant, UserRole.landlord, UserRole.staff})


@router.get("/me", response_model=UserOut, summary="Get current user profile")
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserOut, summary="Update name / phone")
def update_me(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.full_name:
        current_user.full_name = data.full_name.strip()
    if data.phone:
        current_user.phone = data.phone.strip()
    if data.role is not None:
        raw = data.role.strip().lower()
        try:
            new_role = UserRole(raw)
        except ValueError:
            raise HTTPException(400, "Invalid role.")
        if new_role not in _SELF_SERVICE_ROLES:
            raise HTTPException(403, "This role cannot be self-assigned.")
        current_user.role = new_role
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/kyc-documents", summary="Upload validated KYC images (landlord & agent)")
async def upload_kyc_documents(
    id_front: UploadFile = File(..., description="National ID front — any common image format"),
    id_back: UploadFile = File(..., description="National ID back"),
    selfie: UploadFile = File(..., description="Portrait selfie (not a document photo)"),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in (UserRole.landlord, UserRole.staff):
        raise HTTPException(
            status_code=403,
            detail="KYC document upload is required only for landlord and agent accounts.",
        )
    for kind, uf in (("id_front", id_front), ("id_back", id_back), ("selfie", selfie)):
        if not content_type_allowed(uf.content_type):
            raise HTTPException(
                status_code=400,
                detail=f"{kind}: upload an image file (photo from camera or gallery). Received {uf.content_type!r}.",
            )
        raw = await uf.read()
        try:
            jpeg_data = normalize_kyc_image_jpeg(raw, kind)  # type: ignore[arg-type]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{kind}: {exc.args[0]}") from exc
        from app.runtime import upload_root

        out_dir = kyc_user_dir(upload_root(), current_user.id)
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob(f"{kind}.*"):
            try:
                old.unlink()
            except OSError:
                pass
        (out_dir / f"{kind}.jpg").write_bytes(jpeg_data)
    return {"message": "All three documents passed validation and were saved."}


@router.post("/me/kyc-submit", response_model=UserOut, summary="Submit KYC for review after documents uploaded")
def kyc_submit(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role in (UserRole.landlord, UserRole.staff):
        if not kyc_documents_complete(upload_root(), current_user.id):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Upload valid ID (front and back) and a portrait selfie first. "
                    "Photos must be real images with correct framing (ID landscape, selfie portrait) — "
                    "wrong file types, tiny icons, or mismatched slots are rejected automatically."
                ),
            )
    current_user.kyc_submitted_at = datetime.utcnow()
    if current_user.role in (UserRole.landlord, UserRole.staff):
        current_user.kyc_review_status = "pending"
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/change-password", summary="Change password (requires current password)")
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.auth_service import auth_service

    if not auth_service.verify_password(current_password, current_user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    if len(new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters.")
    auth_service.set_password(db, current_user, new_password)
    return {"message": "Password changed successfully."}

