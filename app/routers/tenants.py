from typing import Optional, List

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
import shutil, os, uuid
from datetime import date

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.tenant import TenantOut, TenantCreate, TenantUpdate
from app.services.tenant_service import tenant_service
from app.config import settings
from app.utils.response import success_response

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("", response_model=List[TenantOut])
def list_tenants(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    unit_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tenants with standardized response"""
    tenants = tenant_service.list_tenants(db, current_user.id, search=search, status=status, unit_id=unit_id)
    return success_response(data=tenants)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single tenant with standardized response"""
    tenant = tenant_service.get_tenant(db, tenant_id, current_user.id)
    return success_response(data=tenant)


@router.post("", response_model=TenantOut, status_code=201)
async def create_tenant(
    # Form fields
    unit_id:                 Optional[int]   = Form(None),
    full_name:               str             = Form(...),
    phone:                   str             = Form(...),
    email:                   Optional[str]   = Form(None),
    national_id:             Optional[str]   = Form(None),
    emergency_contact_name:  Optional[str]   = Form(None),
    emergency_contact_phone: Optional[str]   = Form(None),
    lease_start:             str             = Form(...),
    lease_end:               Optional[str]   = Form(None),
    monthly_rent:            float           = Form(...),
    deposit_amount:          float           = Form(0),
    deposit_paid:            bool            = Form(False),
    notes:                   Optional[str]   = Form(None),
    # File upload for deposit receipt
    deposit_receipt:         Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create tenant with standardized response"""
    deposit_receipt_path = None
    if deposit_receipt and deposit_receipt.filename:
        dest = os.path.join(settings.upload_dir, "tenants")
        os.makedirs(dest, exist_ok=True)
        ext = os.path.splitext(deposit_receipt.filename)[1]
        fname = f"{uuid.uuid4().hex}{ext}"
        fpath = os.path.join(dest, fname)
        with open(fpath, "wb") as f:
            shutil.copyfileobj(deposit_receipt.file, f)
        deposit_receipt_path = f"/uploads/tenants/{fname}"

    data = TenantCreate(
        unit_id=unit_id,
        full_name=full_name,
        phone=phone,
        email=email,
        national_id=national_id,
        emergency_contact_name=emergency_contact_name,
        emergency_contact_phone=emergency_contact_phone,
        lease_start=date.fromisoformat(lease_start),
        lease_end=date.fromisoformat(lease_end) if lease_end else None,
        monthly_rent=monthly_rent,
        deposit_amount=deposit_amount,
        deposit_paid=deposit_paid,
        deposit_receipt_path=deposit_receipt_path,
        notes=notes,
    )
    tenant = tenant_service.create_tenant(db, data, current_user.id)
    return success_response(data=tenant, message="Tenant created successfully")


@router.put("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: int,
    unit_id:                 Optional[int]   = Form(None),
    full_name:               Optional[str]   = Form(None),
    phone:                   Optional[str]   = Form(None),
    email:                   Optional[str]   = Form(None),
    national_id:             Optional[str]   = Form(None),
    emergency_contact_name:  Optional[str]   = Form(None),
    emergency_contact_phone: Optional[str]   = Form(None),
    lease_start:             Optional[str]   = Form(None),
    lease_end:               Optional[str]   = Form(None),
    monthly_rent:            Optional[float] = Form(None),
    deposit_amount:          Optional[float] = Form(None),
    deposit_paid:            Optional[bool]  = Form(None),
    notes:                   Optional[str]   = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update tenant with standardized response"""
    patch = {}
    if unit_id is not None:
        patch["unit_id"] = unit_id
    if full_name is not None:
        patch["full_name"] = full_name
    if phone is not None:
        patch["phone"] = phone
    if email is not None:
        patch["email"] = email
    if national_id is not None:
        patch["national_id"] = national_id
    if emergency_contact_name is not None:
        patch["emergency_contact_name"] = emergency_contact_name
    if emergency_contact_phone is not None:
        patch["emergency_contact_phone"] = emergency_contact_phone
    if lease_start is not None:
        patch["lease_start"] = date.fromisoformat(lease_start)
    if lease_end is not None:
        patch["lease_end"] = date.fromisoformat(lease_end)
    if monthly_rent is not None:
        patch["monthly_rent"] = monthly_rent
    if deposit_amount is not None:
        patch["deposit_amount"] = deposit_amount
    if deposit_paid is not None:
        patch["deposit_paid"] = deposit_paid
    if notes is not None:
        patch["notes"] = notes

    updated = tenant_service.update_tenant(db, tenant_id, TenantUpdate(**patch), current_user.id)
    return success_response(data=updated, message="Tenant updated successfully")


@router.post("/{tenant_id}/move-out", response_model=TenantOut)
def move_out(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move out tenant with standardized response"""
    result = tenant_service.move_out_tenant(db, tenant_id, current_user.id)
    return success_response(data=result, message="Tenant moved out successfully")