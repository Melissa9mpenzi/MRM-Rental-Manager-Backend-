"""Admin / staff (agent) workspace APIs — read-only aggregates and admin user directory."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin, require_roles
from app.models.user import User
from app.services.workspace_service import admin_list_users, admin_summary, staff_summary
from app.utils.response import success_response

router = APIRouter(prefix="/workspace", tags=["Workspace"])


@router.get("/admin/summary")
def get_admin_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
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
    _: User = Depends(require_admin),
):
    items, total = admin_list_users(
        db, search=search, role=role, limit=limit, offset=offset
    )
    return success_response(data={"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/staff/summary")
def get_staff_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(["staff", "admin"])),
):
    data = staff_summary(db)
    return success_response(data=data)
