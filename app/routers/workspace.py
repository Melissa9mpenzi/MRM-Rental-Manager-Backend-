"""Admin / staff (agent) workspace APIs — read-only aggregates and admin user directory."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_system_admin, require_roles
from app.models.user import User, UserRole
from app.schemas.auth import UserOut
from app.services.workspace_service import (
    admin_list_properties,
    admin_list_users,
    admin_summary,
    staff_summary,
)
from app.utils.response import success_response

router = APIRouter(prefix="/workspace", tags=["Workspace"])


class KycModerationBody(BaseModel):
    action: str  # approve | reject


@router.get("/admin/summary")
def get_admin_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    data = admin_summary(db)
    return success_response(data=data)


@router.get("/admin/users")
def list_admin_users(
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    items, total = admin_list_users(
        db, search=search, role=role, limit=limit, offset=offset
    )
    return success_response(data={"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/admin/properties")
def list_admin_properties(
    search: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    items, total = admin_list_properties(
        db,
        search=search,
        district=district,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return success_response(data={"items": items, "total": total, "limit": limit, "offset": offset})


@router.patch("/admin/users/{user_id}/kyc-review", summary="Approve or reject landlord/agent KYC")
def admin_kyc_review(
    user_id: int,
    body: KycModerationBody,
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role not in (UserRole.landlord, UserRole.staff):
        raise HTTPException(status_code=400, detail="KYC moderation applies to landlords and agents only.")
    act = (body.action or "").strip().lower()
    if act == "approve":
        user.kyc_review_status = "approved"
        user.trusted_for_commerce = True
    elif act == "reject":
        user.kyc_review_status = "rejected"
        user.trusted_for_commerce = False
    else:
        raise HTTPException(status_code=400, detail="action must be approve or reject.")
    db.commit()
    db.refresh(user)
    return success_response(data=UserOut.model_validate(user).model_dump())


@router.get("/staff/summary")
def get_staff_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(["staff", "system_admin"])),
):
    data = staff_summary(db)
    return success_response(data=data)
