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
        inv, dev_token = gov_invite.create_invitation(
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
    data = {
        "id": inv.id,
        "email": inv.email,
        "agency": inv.agency,
        "role": inv.role.value,
        "status": inv.status.value,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
    }
    if dev_token:
        data["dev_invite_token"] = dev_token
    return success_response(data=data, message="Invitation sent.")


@router.get("/invitations")
def list_officer_invitations(
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    return success_response(data=gov_invite.list_invitations(db))


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


@router.get("/auth/sessions")
def government_login_sessions(
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    return success_response(data=gov_invite.login_sessions_for_user(db))
