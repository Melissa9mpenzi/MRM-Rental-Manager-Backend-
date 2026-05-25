"""
Tenant Portal API Routes
Role-based access for tenants to view their own data only.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.dependencies import require_tenant, get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.property import Property, Unit
from app.models.payment import Payment
from app.schemas.payment import PaymentOut
from app.schemas.tenant import TenantOut, TenantSelfUpdate
from app.services.email_service import send_email
from app.services.auth_service import auth_service
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/tenant", tags=["Tenant Portal"])


def _tenant_self_dict(tenant: Tenant) -> dict:
    status = tenant.status.value if hasattr(tenant.status, "value") else str(tenant.status)
    return {
        "id": tenant.id,
        "full_name": tenant.full_name,
        "phone": tenant.phone,
        "email": tenant.email,
        "national_id": tenant.national_id,
        "emergency_contact_name": tenant.emergency_contact_name,
        "emergency_contact_phone": tenant.emergency_contact_phone,
        "status": status,
        "unit_id": tenant.unit_id,
    }


@router.get("/me")
def get_my_tenant_profile(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db)
):
    """Get the tenant's own profile with standardized response"""
    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise error_response("Tenant profile not found. Contact your landlord.", status_code=404)
    return success_response(data=_tenant_self_dict(tenant))


@router.patch("/me")
def update_my_tenant_profile(
    payload: TenantSelfUpdate,
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """Update contact details on the tenant's rental record (syncs phone to user account)."""
    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise error_response("Tenant profile not found. Contact your landlord.", status_code=404)

    data = payload.model_dump(exclude_none=True)
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(tenant, key, value)

    if "phone" in data and data["phone"]:
        current_user.phone = tenant.phone
    if tenant.full_name:
        current_user.full_name = tenant.full_name

    db.commit()
    db.refresh(tenant)
    db.refresh(current_user)
    return success_response(data=_tenant_self_dict(tenant), message="Tenant profile updated")


@router.get("/my-payments")
def get_my_payments(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db)
):
    """Get payment history for the logged-in tenant with standardized response"""
    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise error_response("Tenant profile not found.", status_code=404)
    
    payments = db.query(Payment).filter(Payment.tenant_id == tenant.id).order_by(Payment.payment_date.desc()).all()
    return success_response(data=payments)


@router.get("/my-invoices")
def get_my_invoices(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db)
):
    """Get invoices for the logged-in tenant with standardized response"""
    from app.models.invoice import Invoice, InvoiceStatus
    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise error_response("Tenant profile not found.", status_code=404)
    
    invoices = db.query(Invoice).filter(
        Invoice.tenant_id == tenant.id,
        Invoice.is_deleted == False
    ).order_by(Invoice.created_at.desc()).all()
    
    data = [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "period_month": inv.period_month,
            "period_year": inv.period_year,
            "due_date": str(inv.due_date),
            "rent_amount": float(inv.rent_amount),
            "penalty_amount": float(inv.penalty_amount),
            "discount_amount": float(inv.discount_amount),
            "total_amount": float(inv.total_amount),
            "amount_paid": float(inv.amount_paid),
            "balance_due": float(inv.balance_due),
            "status": inv.status.value,
            "description": inv.description,
        }
        for inv in invoices
    ]
    return success_response(data=data)


@router.get("/my-lease")
def get_my_lease(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db)
):
    """Get lease details for the tenant with standardized response"""
    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise error_response("Tenant profile not found.", status_code=404)
    
    from app.models.lease import Lease, LeaseStatus
    lease = db.query(Lease).filter(
        Lease.tenant_id == tenant.id,
        Lease.status == LeaseStatus.active
    ).first()
    
    unit = lease.unit if lease else None
    property_obj = unit.parent_property if unit else None
    
    data = {
        "tenant": {
            "id": tenant.id,
            "full_name": tenant.full_name,
            "status": tenant.status.value,
        },
        "lease": {
            "id": lease.id if lease else None,
            "start_date": str(lease.start_date) if lease else None,
            "end_date": str(lease.end_date) if lease else None,
            "monthly_rent": float(lease.monthly_rent) if lease else None,
            "deposit_amount": float(lease.deposit_amount) if lease else None,
            "deposit_paid": lease.deposit_paid if lease else None,
            "status": lease.status.value if lease else None,
        } if lease else None,
        "unit": {
            "id": unit.id,
            "unit_number": unit.unit_number,
            "unit_type": unit.unit_type.value if unit else None,
        } if unit else None,
        "property": {
            "id": property_obj.id,
            "name": property_obj.name,
            "address": property_obj.address,
        } if property_obj else None,
    }
    return success_response(data=data)


@router.get("/admin-view/all-tenants")
def admin_view_all_tenants(
    current_user: User = Depends(require_roles(["system_admin", "landlord"])),
    db: Session = Depends(get_db)
):
    """System administrator / landlord can view tenants with standardized response"""
    if current_user.role == UserRole.system_admin.value:
        tenants = db.query(Tenant).all()
    else:  # landlord
        tenants = db.query(Tenant).filter(Tenant.owner_id == current_user.id).all()
    return success_response(data=tenants)


# ─── TENANT INVITE SYSTEM ────────────────────────────────────────────

class TenantInviteRequest(BaseModel):
    tenant_id: int
    email: EmailStr


class TenantAcceptInviteRequest(BaseModel):
    token: str
    password: str


@router.post("/invite/send", status_code=201)
def send_tenant_invite(
    invite: TenantInviteRequest,
    current_user: User = Depends(require_roles(["system_admin", "landlord"])),
    db: Session = Depends(get_db)
):
    """Landlord sends invite email to tenant to create login account with standardized response"""
    # Verify tenant exists and belongs to this landlord
    tenant = db.query(Tenant).filter(
        Tenant.id == invite.tenant_id,
        Tenant.owner_id == current_user.id
    ).first()
    
    if not tenant:
        raise error_response("Tenant not found or not authorized.", status_code=404)
    
    if tenant.user_id:
        raise error_response("Tenant already has a login account.", status_code=400)
    
    # Generate invite token
    import secrets
    token = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    
    # Store token in tenant record
    tenant.verification_token = token
    tenant.verification_token_expiry = expiry
    db.commit()
    
    # Send invite email
    invite_link = f"http://localhost:5174/tenant/accept-invite?token={token}&email={invite.email}"
    subject = "You're invited to access your rental account"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#f4f7f7;border-radius:12px;">
      <h2 style="color:#161d23;margin-bottom:8px;">Welcome to MRM Rental Manager!</h2>
      <p style="color:#576e6a;margin-bottom:24px;">Your landlord has invited you to access your rental account online.</p>
      <div style="text-align:center;margin:24px 0;">
        <a href="{invite_link}" 
           style="background:#5e8d83;color:#ffffff;padding:16px 32px;border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block;">
          Accept Invitation & Set Password
        </a>
      </div>
      <p style="color:#576e6a;margin-top:24px;font-size:13px;">This link expires in <strong>7 days</strong>. If you didn't expect this, ignore this email.</p>
    </div>
    """
    
    sent = send_email(invite.email, subject, html)
    if not sent:
        raise error_response("Failed to send invite email.", status_code=500)
    
    # Update tenant email if different
    tenant.email = invite.email
    db.commit()
    
    return success_response(data={"email": invite.email}, message="Invite sent successfully")


@router.post("/invite/accept", status_code=201)
def accept_tenant_invite(
    accept: TenantAcceptInviteRequest,
    db: Session = Depends(get_db)
):
    """Tenant accepts invite and creates login account with standardized response"""
    if len(accept.password) < 6:
        raise error_response("Password must be at least 6 characters.", status_code=400)
    
    # Find tenant by token
    tenant = db.query(Tenant).filter(Tenant.verification_token == accept.token).first()
    
    if not tenant:
        raise error_response("Invalid or expired invite token.", status_code=400)
    
    # Check token expiry
    if tenant.verification_token_expiry:
        if tenant.verification_token_expiry.tzinfo is None:
            expiry = tenant.verification_token_expiry.replace(tzinfo=timezone.utc)
        else:
            expiry = tenant.verification_token_expiry
        
        if datetime.now(timezone.utc) > expiry:
            raise error_response("Invite token has expired. Contact your landlord.", status_code=400)
    
    if tenant.user_id:
        raise error_response("Tenant account already activated.", status_code=400)
    
    # Create user account for tenant
    user = User(
        email=tenant.email,
        full_name=tenant.full_name,
        phone=tenant.phone,
        password_hash=auth_service.hash_password(accept.password),
        role=UserRole.tenant,
        email_verified=True,
        trusted_for_commerce=True,
        kyc_review_status="none",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Link tenant to user
    tenant.user_id = user.id
    tenant.verification_token = None
    tenant.verification_token_expiry = None
    db.commit()
    
    return success_response(data={"email": user.email}, message="Account created successfully. You can now log in.")


@router.get("/invite/verify")
def verify_invite_token(token: str, db: Session = Depends(get_db)):
    """Verify invite token is valid (for frontend check) with standardized response"""
    tenant = db.query(Tenant).filter(Tenant.verification_token == token).first()
    
    if not tenant:
        raise error_response("Invalid token.", status_code=400)
    
    if tenant.user_id:
        raise error_response("Token already used.", status_code=400)
    
    if tenant.verification_token_expiry:
        if tenant.verification_token_expiry.tzinfo is None:
            expiry = tenant.verification_token_expiry.replace(tzinfo=timezone.utc)
        else:
            expiry = tenant.verification_token_expiry
        
        if datetime.now(timezone.utc) > expiry:
            raise error_response("Token expired.", status_code=400)
    
    return success_response(data={"valid": True, "email": tenant.email, "full_name": tenant.full_name})
