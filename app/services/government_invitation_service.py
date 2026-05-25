"""Invitation-only government officer provisioning."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.government_invitation import GovernmentInvitation, InvitationStatus
from app.models.gov_login_session import GovLoginSession
from app.models.user import User, UserRole, is_government_officer, is_system_admin
from app.schemas.auth import UserOut
from app.services.audit_service import log_action
from app.services.auth_service import auth_service
from app.services.email_service import (
    generate_otp,
    generate_verification_token,
    send_government_2fa_otp,
    send_government_invitation_email,
    smtp_is_configured,
)

AGENCY_ROLE_MAP = {
    "nira": UserRole.gov_nira,
    "kcca": UserRole.gov_kcca,
    "ura": UserRole.gov_ura,
}

GOV_2FA_OTP_MINUTES = 15


def _utc_now_naive() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns (consistent read/write)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_otp_digits(code: str) -> str:
    digits = "".join(c for c in (code or "") if c.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _otp_expiry_naive(exp: Optional[datetime]) -> Optional[datetime]:
    if not exp:
        return None
    if exp.tzinfo is not None:
        return exp.astimezone(timezone.utc).replace(tzinfo=None)
    return exp


def issue_and_email_gov_2fa_otp(db: Session, user: User) -> tuple[str, bool]:
    """Generate a 6-digit portal 2FA code, store on user, email to official address."""
    otp = generate_otp()
    expiry = _utc_now_naive() + timedelta(minutes=GOV_2FA_OTP_MINUTES)
    user.gov_2fa_otp = otp
    user.gov_2fa_otp_expiry = expiry
    db.commit()
    db.refresh(user)

    sent = send_government_2fa_otp(
        to_email=user.email,
        full_name=user.full_name,
        otp=otp,
    )
    if not sent:
        print(
            f"\n[WARN] Government 2FA email was NOT sent (check SMTP in .env).\n"
            f"       Officer: {user.email}\n"
            f"       Sign-in code (valid {GOV_2FA_OTP_MINUTES} min): {otp}\n"
        )
    return otp, sent


def _government_portal_url(path_suffix: str = "/login") -> str:
    base = settings.frontend_base_url.rstrip("/")
    portal = settings.government_portal_path.strip()
    if portal.startswith("http"):
        root = portal.rsplit("/", 1)[0] if "/login" in portal else portal
        return f"{root}{path_suffix}"
    return f"{base}{portal.replace('/login', '')}{path_suffix}"


def invite_url_for(inv: GovernmentInvitation) -> str:
    return f"{_government_portal_url('/accept-invite')}?token={inv.token}"


def _send_invitation_email(inv: GovernmentInvitation) -> bool:
    role = inv.role.value if hasattr(inv.role, "value") else str(inv.role)
    return send_government_invitation_email(
        inv.email,
        full_name=inv.full_name,
        agency=(inv.agency or "").upper(),
        role_label=role.replace("gov_", "").upper(),
        invite_url=invite_url_for(inv),
        work_id=inv.work_id,
    )


def _role_for_agency(agency: str, role: UserRole) -> UserRole:
    agency = agency.lower().strip()
    if role == UserRole.system_admin:
        raise ValueError("System administrator accounts are seed-only and cannot be invited.")
    expected = AGENCY_ROLE_MAP.get(agency)
    if expected and role != expected:
        raise ValueError(f"Role {role.value} does not match agency {agency}.")
    if role not in (UserRole.gov_nira, UserRole.gov_kcca, UserRole.gov_ura):
        raise ValueError("Invalid government officer role.")
    return role


def _ip_allowed(client_ip: Optional[str]) -> bool:
    raw = (settings.government_allowed_ips or "").strip()
    if not raw:
        return True
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return client_ip in allowed if client_ip else False


def record_gov_login_attempt(
    db: Session,
    *,
    email: str,
    success: bool,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> None:
    db.add(
        GovLoginSession(
            email=email,
            user_id=user_id,
            success=success,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500] or None,
            failure_reason=failure_reason,
        )
    )
    db.commit()


def create_invitation(
    db: Session,
    *,
    inviter: User,
    full_name: str,
    email: str,
    phone: Optional[str],
    agency: str,
    role: UserRole,
    work_id: str,
) -> tuple[GovernmentInvitation, dict[str, Any]]:
    email = email.strip().lower()
    agency = agency.lower().strip()
    role = _role_for_agency(agency, role)

    if db.query(User).filter(User.email == email).first():
        raise ValueError("An account with this email already exists.")
    pending = (
        db.query(GovernmentInvitation)
        .filter(
            GovernmentInvitation.email == email,
            GovernmentInvitation.status == InvitationStatus.pending,
        )
        .first()
    )
    if pending:
        raise ValueError("A pending invitation already exists for this email.")

    token = generate_verification_token(40)
    expiry = datetime.now(timezone.utc) + timedelta(days=7)
    inv = GovernmentInvitation(
        email=email,
        full_name=full_name.strip(),
        phone=phone,
        agency=agency,
        role=role,
        work_id=work_id.strip(),
        token=token,
        status=InvitationStatus.pending,
        invited_by_id=inviter.id,
        expires_at=expiry,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    invite_url = invite_url_for(inv)
    email_sent = _send_invitation_email(inv)
    if not email_sent:
        print(
            f"\n[WARN] Government invitation email was NOT sent to {email!r}.\n"
            f"       Configure SMTP in .env (SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM).\n"
            f"       Invite link: {invite_url}\n"
        )
    log_action(
        db,
        user_id=inviter.id,
        action="gov_invitation_created",
        table_name="government_invitations",
        record_id=inv.id,
        new_value={
            "email": email,
            "agency": agency,
            "role": role.value,
            "email_sent": email_sent,
        },
    )
    meta: dict[str, Any] = {
        "email_sent": email_sent,
        "invite_url": invite_url,
    }
    if settings.environment == "development":
        meta["dev_invite_token"] = token
    return inv, meta


def list_invitations(db: Session, *, limit: int = 50) -> dict[str, Any]:
    rows = (
        db.query(GovernmentInvitation)
        .order_by(GovernmentInvitation.created_at.desc())
        .limit(limit)
        .all()
    )
    items: list[dict[str, Any]] = []
    for r in rows:
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        row: dict[str, Any] = {
            "id": r.id,
            "email": r.email,
            "full_name": r.full_name,
            "agency": r.agency,
            "role": r.role.value if hasattr(r.role, "value") else str(r.role),
            "work_id": r.work_id,
            "status": status,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        if status == InvitationStatus.pending.value:
            row["invite_url"] = invite_url_for(r)
            row["can_resend"] = True
        items.append(row)
    return {
        "smtp_configured": smtp_is_configured(),
        "frontend_base_url": settings.frontend_base_url,
        "items": items,
    }


def resend_invitation_email(
    db: Session,
    *,
    invitation_id: int,
    inviter: User,
) -> tuple[GovernmentInvitation, dict[str, Any]]:
    inv = db.get(GovernmentInvitation, invitation_id)
    if not inv:
        raise ValueError("Invitation not found.")
    if inv.status != InvitationStatus.pending:
        raise ValueError("Only pending invitations can be resent.")
    now = datetime.now(timezone.utc)
    exp = inv.expires_at
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if inv.status == InvitationStatus.expired or (exp and now > exp):
        inv.status = InvitationStatus.expired
        db.commit()
        raise ValueError("This invitation has expired. Create a new invitation for this officer.")
    invite_url = invite_url_for(inv)
    email_sent = _send_invitation_email(inv)
    if not email_sent:
        print(
            f"\n[WARN] Government invitation resend email was NOT sent to {inv.email!r}.\n"
            f"       Configure SMTP in .env (SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM).\n"
            f"       Invite link: {invite_url}\n"
        )
    log_action(
        db,
        user_id=inviter.id,
        action="gov_invitation_resent",
        table_name="government_invitations",
        record_id=inv.id,
        new_value={"email": inv.email, "email_sent": email_sent},
    )
    meta: dict[str, Any] = {"email_sent": email_sent, "invite_url": invite_url}
    if settings.environment == "development" and not email_sent:
        meta["dev_invite_token"] = inv.token
    return inv, meta


def verify_invitation_token(db: Session, token: str) -> dict[str, Any]:
    inv = db.query(GovernmentInvitation).filter(GovernmentInvitation.token == token.strip()).first()
    if not inv:
        raise ValueError("Invalid or unknown invitation.")
    now = datetime.now(timezone.utc)
    exp = inv.expires_at
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if inv.status == InvitationStatus.revoked:
        raise ValueError("This invitation has been revoked.")
    if inv.status == InvitationStatus.accepted:
        raise ValueError("This invitation was already used.")
    if inv.status == InvitationStatus.expired or (exp and now > exp):
        inv.status = InvitationStatus.expired
        db.commit()
        raise ValueError("This invitation has expired. Contact the platform administrator.")
    return {
        "email": inv.email,
        "full_name": inv.full_name,
        "agency": inv.agency,
        "role": inv.role.value if hasattr(inv.role, "value") else str(inv.role),
        "work_id": inv.work_id,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
    }


def accept_invitation(
    db: Session,
    *,
    token: str,
    password: str,
    security_pin: str,
    work_id_confirm: str,
) -> User:
    inv = db.query(GovernmentInvitation).filter(GovernmentInvitation.token == token.strip()).first()
    if not inv:
        raise ValueError("Invalid invitation.")
    verify_invitation_token(db, token)
    if work_id_confirm.strip() != inv.work_id:
        raise ValueError("Work ID does not match the invitation record.")

    if db.query(User).filter(User.email == inv.email).first():
        raise ValueError("An account already exists for this email.")

    user = User(
        email=inv.email,
        full_name=inv.full_name,
        phone=inv.phone,
        role=inv.role,
        password_hash=auth_service.hash_password(password),
        email_verified=True,
        is_active=True,
        trusted_for_commerce=False,
        kyc_review_status="none",
        gov_agency=inv.agency,
        gov_work_id=inv.work_id,
        gov_security_pin_hash=auth_service.hash_password(security_pin),
        gov_2fa_enabled=True,
        gov_onboarding_complete=True,
    )
    db.add(user)
    inv.status = InvitationStatus.accepted
    inv.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    log_action(
        db,
        user_id=user.id,
        action="gov_invitation_accepted",
        table_name="government_invitations",
        record_id=inv.id,
        new_value={"email": user.email, "role": user.role.value},
    )
    return user


def government_login(
    db: Session,
    *,
    email: str,
    password: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    email = email.strip().lower()
    if not _ip_allowed(ip_address):
        record_gov_login_attempt(
            db,
            email=email,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="ip_blocked",
        )
        raise ValueError("Access denied from this network location.")

    user = auth_service.authenticate(db, email, password)
    if not user:
        record_gov_login_attempt(
            db,
            email=email,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="invalid_credentials",
        )
        raise ValueError("Invalid email or password.")
    if is_system_admin(user.role):
        record_gov_login_attempt(
            db,
            email=email,
            success=False,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="system_admin_use_main_login",
        )
        raise ValueError(
            "System administrators sign in at the main RentDirect login, not the government portal."
        )
    if not is_government_officer(user.role):
        record_gov_login_attempt(
            db,
            email=email,
            success=False,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="not_government_account",
        )
        raise ValueError("This account is not authorized for the government portal.")
    if not user.is_active:
        raise ValueError("Account is disabled.")
    if not user.gov_onboarding_complete:
        raise ValueError("Complete your invitation onboarding before signing in.")

    tokens = auth_service.create_tokens(db, user)
    otp, otp_email_sent = issue_and_email_gov_2fa_otp(db, user)
    record_gov_login_attempt(
        db,
        email=email,
        success=True,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    log_action(
        db,
        user_id=user.id,
        action="gov_login",
        table_name="users",
        record_id=user.id,
        ip_address=ip_address,
        new_value={"user_agent": (user_agent or "")[:200]},
    )
    payload: dict[str, Any] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "user": UserOut.model_validate(user).model_dump(),
        "needs_government_2fa": True,
        "otp_email_sent": otp_email_sent,
    }
    if not otp_email_sent and settings.environment == "development":
        payload["dev_gov_2fa_otp"] = otp
    return payload


def resend_government_2fa_otp(db: Session, user: User) -> dict[str, Any]:
    if not is_government_officer(user.role) and not is_system_admin(user.role):
        raise ValueError("Two-factor codes are only for government portal accounts.")
    otp, sent = issue_and_email_gov_2fa_otp(db, user)
    out: dict[str, Any] = {"otp_email_sent": sent, "email": user.email}
    if not sent and settings.environment == "development":
        out["dev_gov_2fa_otp"] = otp
    return out


def verify_government_2fa(db: Session, user: User, code: str) -> None:
    digits = _normalize_otp_digits(code)
    if len(digits) < 6:
        raise ValueError("Enter the 6-digit code from your email.")
    if not is_government_officer(user.role) and not is_system_admin(user.role):
        raise ValueError("This account is not authorized for government portal 2FA.")

    db_user = db.get(User, user.id)
    if not db_user:
        raise ValueError("User account not found.")

    stored = (db_user.gov_2fa_otp or "").strip()
    exp = _otp_expiry_naive(db_user.gov_2fa_otp_expiry)
    now = _utc_now_naive()

    if not stored:
        from app.models.audit import AuditLog

        recent_verify = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == db_user.id,
                AuditLog.action == "gov_2fa_verified",
                AuditLog.created_at >= now - timedelta(minutes=5),
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        if recent_verify:
            return
        raise ValueError(
            "No active verification code. Sign in again or tap “Resend code” for a new email."
        )

    if not exp or now > exp:
        raise ValueError(
            "This code has expired. Tap “Resend code to my email” or sign in again for a new code."
        )

    if digits != stored[:6]:
        raise ValueError(
            "That code does not match. Use the code from your most recent email "
            "(resend or sign-in sends a new one)."
        )

    db_user.gov_2fa_otp = None
    db_user.gov_2fa_otp_expiry = None
    db.commit()
    log_action(
        db,
        user_id=db_user.id,
        action="gov_2fa_verified",
        table_name="users",
        record_id=db_user.id,
    )


def login_sessions_for_user(db: Session, *, limit: int = 50) -> list[dict]:
    rows = (
        db.query(GovLoginSession)
        .order_by(GovLoginSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "email": r.email,
            "success": r.success,
            "ip_address": r.ip_address,
            "user_agent": r.user_agent,
            "failure_reason": r.failure_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
