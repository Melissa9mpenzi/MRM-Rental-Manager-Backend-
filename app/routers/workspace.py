"""Admin / staff (agent) workspace APIs — read-only aggregates and admin user directory."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_system_admin, require_roles
from app.models.user import User, UserRole
from app.schemas.auth import UserOut
from app.services import agent_crm_service
from app.services.workspace_service import (
    admin_list_properties,
    admin_list_users,
    admin_summary,
    admin_user_account_action,
    admin_delete_user,
    staff_summary,
)
from app.schemas.agent_crm import (
    ClientCreate,
    ClientUpdate,
    CommissionCreate,
    CommissionUpdate,
    DealCreate,
    DealUpdate,
    LeadCreate,
    LeadUpdate,
    ScheduleCreate,
    ScheduleUpdate,
)
from app.utils.response import success_response

router = APIRouter(prefix="/workspace", tags=["Workspace"])


class KycModerationBody(BaseModel):
    action: str  # approve | reject


class AdminUserAccountBody(BaseModel):
    action: str  # disconnect | reconnect


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


@router.patch("/admin/users/{user_id}/account", summary="Disconnect or reconnect a platform account")
def admin_user_account(
    user_id: int,
    body: AdminUserAccountBody,
    db: Session = Depends(get_db),
    actor: User = Depends(require_system_admin),
):
    data = admin_user_account_action(
        db,
        actor_id=actor.id,
        target_user_id=user_id,
        action=body.action,
    )
    return success_response(data=data, message=data.get("message"))


@router.delete("/admin/users/{user_id}", summary="Permanently delete a platform account")
def admin_user_delete(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_system_admin),
):
    data = admin_delete_user(db, actor_id=actor.id, target_user_id=user_id)
    return success_response(data=data, message=data.get("message"))


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
        from datetime import datetime

        user.kyc_review_status = "approved"
        user.trusted_for_commerce = True
        if not user.kyc_submitted_at:
            user.kyc_submitted_at = datetime.utcnow()
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
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner_id = current_user.id if current_user.role == UserRole.staff else None
    data = staff_summary(db, owner_id=owner_id)
    return success_response(data=data)


def _staff_owner(user: User) -> int:
    if user.role not in (UserRole.staff, UserRole.system_admin):
        raise HTTPException(status_code=403, detail="Staff access only.")
    return user.id


@router.get("/staff/leads")
def staff_list_leads(
    stage: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.list_leads(db, owner, stage=stage, q=q))


@router.post("/staff/leads", status_code=201)
def staff_create_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.create_lead(db, owner, payload), message="Lead created")


@router.patch("/staff/leads/{lead_id}")
def staff_update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.update_lead(db, owner, lead_id, payload), message="Lead updated")


@router.delete("/staff/leads/{lead_id}")
def staff_delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    agent_crm_service.delete_lead(db, owner, lead_id)
    return success_response(message="Lead deleted")


@router.get("/staff/clients")
def staff_list_clients(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.list_clients(db, owner, q=q))


@router.post("/staff/clients", status_code=201)
def staff_create_client(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.create_client(db, owner, payload), message="Client created")


@router.patch("/staff/clients/{client_id}")
def staff_update_client(
    client_id: int,
    payload: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(
        data=agent_crm_service.update_client(db, owner, client_id, payload), message="Client updated"
    )


@router.get("/staff/schedules")
def staff_list_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.list_schedules(db, owner))


@router.post("/staff/schedules", status_code=201)
def staff_create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(
        data=agent_crm_service.create_schedule(db, owner, payload), message="Event scheduled"
    )


@router.patch("/staff/schedules/{event_id}")
def staff_update_schedule(
    event_id: int,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(
        data=agent_crm_service.update_schedule(db, owner, event_id, payload), message="Event updated"
    )


@router.get("/staff/deals")
def staff_list_deals(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.list_deals(db, owner, status=status))


@router.post("/staff/deals", status_code=201)
def staff_create_deal(
    payload: DealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.create_deal(db, owner, payload), message="Deal created")


@router.patch("/staff/deals/{deal_id}")
def staff_update_deal(
    deal_id: int,
    payload: DealUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.update_deal(db, owner, deal_id, payload), message="Deal updated")


@router.get("/staff/commissions")
def staff_list_commissions(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.list_commissions(db, owner, status=status))


@router.post("/staff/commissions", status_code=201)
def staff_create_commission(
    payload: CommissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(
        data=agent_crm_service.create_commission(db, owner, payload), message="Commission recorded"
    )


@router.patch("/staff/commissions/{commission_id}")
def staff_update_commission(
    commission_id: int,
    payload: CommissionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(
        data=agent_crm_service.update_commission(db, owner, commission_id, payload),
        message="Commission updated",
    )


@router.get("/staff/analytics")
def staff_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["staff", "system_admin"])),
):
    owner = _staff_owner(current_user)
    return success_response(data=agent_crm_service.analytics(db, owner))
