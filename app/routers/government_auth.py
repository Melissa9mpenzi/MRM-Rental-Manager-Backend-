"""Public government portal auth — invitation accept & secure login (no public signup)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_system_admin
from app.models.user import User
from app.schemas.government_auth import (
    AcceptGovInvitationBody,
    CreateGovInvitationBody,
    GovernmentLoginBody,
    GovernmentTwoFaBody,
)
from app.services import government_invitation_service as gov_invite
from app.utils.response import error_response, success_response

router = APIRouter(prefix="/government", tags=["Government Auth"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/invitations", status_code=201)
def create_officer_invitation(
    body: CreateGovInvitationBody,
    db: Session = Depends(get_db),
    inviter: User = Depends(require_system_admin),
):
    try:
        inv, meta = gov_invite.create_invitation(
            db,
            inviter=inviter,
            full_name=body.full_name,
            email=str(body.email),
            phone=body.phone,
            agency=body.agency,
            role=body.role,
            work_id=body.work_id,
        )
    except ValueError as e:
        raise error_response(str(e), status_code=400) from e
    email_sent = bool(meta.get("email_sent"))
    data = {
        "id": inv.id,
        "email": inv.email,
        "agency": inv.agency,
        "role": inv.role.value,
        "status": inv.status.value,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "email_sent": email_sent,
    }
    if meta.get("dev_invite_token"):
        data["dev_invite_token"] = meta["dev_invite_token"]
    if meta.get("invite_url"):
        data["invite_url"] = meta["invite_url"]
    if email_sent:
        message = f"Invitation email sent to {inv.email}."
    else:
        message = (
            "Invitation saved, but the email could not be sent. "
            "Configure SMTP in the backend .env file, or use the invite link below."
        )
    return success_response(data=data, message=message)


@router.get("/invitations")
def list_officer_invitations(
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    return success_response(data=gov_invite.list_invitations(db))


@router.post("/invitations/{invitation_id}/resend")
def resend_officer_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    inviter: User = Depends(require_system_admin),
):
    try:
        inv, meta = gov_invite.resend_invitation_email(
            db, invitation_id=invitation_id, inviter=inviter
        )
    except ValueError as e:
        raise error_response(str(e), status_code=400) from e
    email_sent = bool(meta.get("email_sent"))
    data = {
        "id": inv.id,
        "email": inv.email,
        "status": inv.status.value,
        "email_sent": email_sent,
        "invite_url": meta.get("invite_url"),
    }
    if meta.get("dev_invite_token"):
        data["dev_invite_token"] = meta["dev_invite_token"]
    if email_sent:
        message = f"Invitation email resent to {inv.email}."
    else:
        message = (
            "Could not send the invitation email. Configure SMTP on the backend "
            "(SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM) or copy the invite link below."
        )
    return success_response(data=data, message=message)


@router.get("/invitation/verify")
def verify_officer_invitation(token: str, db: Session = Depends(get_db)):
    try:
        data = gov_invite.verify_invitation_token(db, token)
    except ValueError as e:
        raise error_response(str(e), status_code=400) from e
    return success_response(data=data)


@router.post("/invitation/accept", status_code=201)
def accept_officer_invitation(body: AcceptGovInvitationBody, db: Session = Depends(get_db)):
    try:
        user = gov_invite.accept_invitation(
            db,
            token=body.token,
            password=body.password,
            security_pin=body.security_pin,
            work_id_confirm=body.work_id_confirm,
        )
    except ValueError as e:
        raise error_response(str(e), status_code=400) from e
    return success_response(
        data={"email": user.email, "role": user.role.value},
        message="Account activated. Sign in at the government portal.",
    )


@router.post("/auth/login")
def government_portal_login(
    body: GovernmentLoginBody,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        data = gov_invite.government_login(
            db,
            email=str(body.email),
            password=body.password,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise error_response(str(e), status_code=401) from e
    return success_response(data=data)


@router.post("/auth/verify-2fa")
def government_verify_2fa(
    body: GovernmentTwoFaBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        gov_invite.verify_government_2fa(db, current_user, body.code)
    except ValueError as e:
        raise error_response(str(e), status_code=400) from e
    return success_response(message="Two-factor verification recorded.")


@router.post("/auth/resend-2fa")
def government_resend_2fa(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        data = gov_invite.resend_government_2fa_otp(db, current_user)
    except ValueError as e:
        raise error_response(str(e), status_code=400) from e
    if data.get("otp_email_sent"):
        message = f"New verification code sent to {current_user.email}."
    else:
        message = (
            "Could not send email — check SMTP settings. "
            "In development, use the code shown in the API terminal or dev_gov_2fa_otp in the response."
        )
    return success_response(data=data, message=message)


@router.get("/auth/sessions")
def government_login_sessions(
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    return success_response(data=gov_invite.login_sessions_for_user(db))
