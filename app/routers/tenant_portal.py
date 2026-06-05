"""
Tenant Portal API Routes
Role-based access for tenants to view their own data only.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
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
from app.services.public_url_service import frontend_base_url
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/tenant", tags=["Tenant Portal"])


def _norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _find_unlinked_tenant_for_email(db: Session, email: str) -> Tenant | None:
    norm = _norm_email(email)
    if not norm:
        return None
    return (
        db.query(Tenant)
        .filter(Tenant.user_id.is_(None))
        .filter(func.lower(Tenant.email) == norm)
        .order_by(Tenant.id.desc())
        .first()
    )


def _pending_invitation_payload(db: Session, tenant: Tenant) -> dict:
    unit = tenant.unit
    property_obj = unit.parent_property if unit else None
    return {
        "tenant_id": tenant.id,
        "full_name": tenant.full_name,
        "email": tenant.email,
        "monthly_rent": float(tenant.monthly_rent) if tenant.monthly_rent is not None else None,
        "lease_start": str(tenant.lease_start) if tenant.lease_start else None,
        "unit": {
            "id": unit.id,
            "unit_number": unit.unit_number,
        }
        if unit
        else None,
        "property": {
            "id": property_obj.id,
            "name": property_obj.name,
            "address": property_obj.address,
        }
        if property_obj
        else None,
    }


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


@router.post("/reconnect")
def reconnect_tenant_profile(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """
    Link the landlord's tenant record to the currently logged-in account (same email).
    Use when you already accepted an invite but sign in with Google/Privy or a different method.
    """
    from app.services.invoice_service import resolve_tenant_for_user

    before = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    tenant = resolve_tenant_for_user(db, current_user)
    if not tenant:
        raise error_response(
            f"No rental record found for {current_user.email}. "
            "Ask your landlord to add you as a tenant with this exact email, then resend the invite.",
            status_code=404,
        )
    return success_response(
        data={
            **_tenant_self_dict(tenant),
            "was_already_linked": before is not None and before.id == tenant.id,
            "relinked": before is None,
        },
        message="Rental record linked to this login."
        if before is None
        else "Your rental record is already linked to this login.",
    )


@router.get("/pending-invitation")
def get_pending_invitation(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """
    Rental waiting to be linked to this login (same email, no portal account yet).
    Shown on the tenant dashboard so acceptance does not require the email link.
    """
    from app.services.invoice_service import resolve_tenant_for_user

    linked = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if linked or resolve_tenant_for_user(db, current_user):
        return success_response(data=None, message="Already linked to a rental record.")

    pending = _find_unlinked_tenant_for_email(db, current_user.email)
    if not pending:
        return success_response(data=None, message="No pending invitation for this email.")

    return success_response(
        data=_pending_invitation_payload(db, pending),
        message="You have a rental invitation waiting.",
    )


@router.post("/accept-rental")
def accept_rental_in_app(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """Link the landlord's tenant record to the logged-in account (no email token required)."""
    from app.services.invoice_service import resolve_tenant_for_user

    existing = resolve_tenant_for_user(db, current_user)
    if existing:
        return success_response(
            data={**_tenant_self_dict(existing), "already_linked": True},
            message="Your rental record is already linked to this login.",
        )

    pending = _find_unlinked_tenant_for_email(db, current_user.email)
    if not pending:
        raise error_response(
            f"No rental invitation found for {current_user.email}. "
            "Ask your landlord to add you with this exact email, then try again.",
            status_code=404,
        )

    pending.user_id = current_user.id
    pending.verification_token = None
    pending.verification_token_expiry = None
    if not pending.phone and getattr(current_user, "phone", None):
        pending.phone = current_user.phone
    if pending.full_name and not current_user.full_name:
        current_user.full_name = pending.full_name
    db.commit()
    db.refresh(pending)

    return success_response(
        data={**_tenant_self_dict(pending), "already_linked": False},
        message="Rental linked. You can pay rent and view your lease from the dashboard.",
    )


@router.get("/me")
def get_my_tenant_profile(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db)
):
    """Get the tenant's own profile with standardized response"""
    from app.services.invoice_service import resolve_tenant_for_user

    tenant = resolve_tenant_for_user(db, current_user)
    if not tenant:
        raise error_response(
            "No rental record linked to this login. Accept your landlord invite first.",
            status_code=404,
        )
    return success_response(data=_tenant_self_dict(tenant))


@router.patch("/me")
def update_my_tenant_profile(
    payload: TenantSelfUpdate,
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db),
):
    """Update contact details on the tenant's rental record (syncs phone to user account)."""
    from app.services.invoice_service import resolve_tenant_for_user

    tenant = resolve_tenant_for_user(db, current_user)
    if not tenant:
        raise error_response(
            "No rental record linked to this login. Accept your landlord invite first.",
            status_code=404,
        )

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
    from app.services.invoice_service import resolve_tenant_for_user

    tenant = resolve_tenant_for_user(db, current_user)
    if not tenant:
        return success_response(data=[], message="No rental record yet — payments appear after your landlord assigns a unit.")
    
    payments = db.query(Payment).filter(Payment.tenant_id == tenant.id).order_by(Payment.payment_date.desc()).all()
    out = [
        {
            "id": p.id,
            "amount": float(p.amount or 0),
            "payment_type": p.payment_type.value if hasattr(p.payment_type, "value") else str(p.payment_type),
            "payment_method": p.payment_method.value if hasattr(p.payment_method, "value") else str(p.payment_method),
            "reference": p.reference,
            "period_month": p.period_month,
            "period_year": p.period_year,
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
            "notes": p.notes,
        }
        for p in payments
    ]
    return success_response(data=out)


@router.get("/my-invoices")
def get_my_invoices(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db),
    ensure_current: bool = True,
):
    """Get invoices for the logged-in tenant with standardized response"""
    from app.models.invoice import Invoice
    from app.services.invoice_service import (
        ensure_current_rent_invoice,
        resolve_tenant_for_user,
        serialize_invoice,
    )

    tenant = resolve_tenant_for_user(db, current_user)
    if not tenant:
        raise error_response(
            "No rental record linked to this login. Accept your landlord invite first.",
            status_code=404,
        )

    if ensure_current:
        try:
            ensure_current_rent_invoice(db, tenant)
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("ensure_current_rent_invoice: %s", exc)

    invoices = (
        db.query(Invoice)
        .filter(Invoice.tenant_id == tenant.id, Invoice.is_deleted == False)
        .order_by(Invoice.created_at.desc())
        .all()
    )

    return success_response(data=[serialize_invoice(inv) for inv in invoices])


@router.get("/my-lease")
def get_my_lease(
    current_user: User = Depends(require_tenant),
    db: Session = Depends(get_db)
):
    """Get lease details for the tenant with standardized response"""
    from app.services.invoice_service import resolve_tenant_for_user

    tenant = resolve_tenant_for_user(db, current_user)
    if not tenant:
        raise error_response(
            "No rental record linked to this login. Accept your landlord invite first.",
            status_code=404,
        )

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
            "photo_path": property_obj.photo_path,
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

    tenant.email = str(invite.email).strip()
    
    # Generate invite token
    import secrets
    token = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    
    # Store token in tenant record
    tenant.verification_token = token
    tenant.verification_token_expiry = expiry
    db.commit()
    
    # Send invite email (optional — tenant can accept on dashboard when logged in)
    invite_link = f"{frontend_base_url()}/tenant/accept-invite?token={token}&email={invite.email}"
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

    return success_response(
        data={
            "email": invite.email,
            "email_sent": bool(sent),
            "dashboard_accept": True,
        },
        message=(
            "Invite sent by email."
            if sent
            else "Invite is ready — tenant can sign in with this email and accept it on their dashboard."
        ),
    )


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
    
    email = (tenant.email or "").strip().lower()
    if not email:
        raise error_response(
            "This invite has no email on file. Ask your landlord to resend the invite to your email address.",
            status_code=400,
        )

    if tenant.user_id:
        linked = db.query(User).filter(User.id == tenant.user_id).first()
        tokens = auth_service.create_tokens(db, linked) if linked else None
        return success_response(
            data={
                "email": linked.email if linked else email,
                "already_active": True,
                "access_token": tokens["access_token"] if tokens else None,
                "refresh_token": tokens["refresh_token"] if tokens else None,
            },
            message="This invite was already accepted. Sign in with the same email you used before.",
        )

    from sqlalchemy import func

    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing:
        role_val = existing.role.value if hasattr(existing.role, "value") else str(existing.role)
        if role_val != UserRole.tenant.value:
            raise error_response(
                "This email is registered as a non-tenant account. Use a different email or contact support.",
                status_code=400,
            )
        existing.password_hash = auth_service.hash_password(accept.password)
        existing.email_verified = True
        existing.full_name = tenant.full_name or existing.full_name
        if tenant.phone:
            existing.phone = tenant.phone
        tenant.user_id = existing.id
        tenant.verification_token = None
        tenant.verification_token_expiry = None
        db.commit()
        db.refresh(existing)
        tokens = auth_service.create_tokens(db, existing)
        return success_response(
            data={
                "email": existing.email,
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "linked_existing_account": True,
            },
            message="Rental record linked to your existing account. You are signed in.",
        )

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

    tenant.user_id = user.id
    tenant.verification_token = None
    tenant.verification_token_expiry = None
    db.commit()

    tokens = auth_service.create_tokens(db, user)
    return success_response(
        data={
            "email": user.email,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        },
        message="Account created. You are signed in.",
    )


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
