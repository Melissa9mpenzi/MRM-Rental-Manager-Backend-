from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_db
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    UserOut,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailTokenBody,
    FirebaseSignInBody,
)
from app.services.auth_service import auth_service
from app.services.email_service import (
    generate_otp, send_registration_verification_link, send_password_reset_otp,
    generate_verification_token
)
from app.dependencies import get_current_user
from app.models.user import User, UserRole, is_government_officer, is_system_admin
from app.utils.security import decode_token
from app.utils.response import success_response, error_response
from app.services.firebase_token_service import verify_firebase_id_token

router = APIRouter(prefix="/auth", tags=["Auth"])


def _login_redirect(**params: str) -> str:
    base = settings.frontend_base_url.rstrip("/")
    q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v is not None)
    return f"{base}/login?{q}"


def _expiry_utc(exp):
    if not exp:
        return None
    if exp.tzinfo is None:
        return exp.replace(tzinfo=timezone.utc)
    return exp


def _email_verification_secret_accepted(user: User, submitted: str, now: datetime) -> bool:
    """True if submitted value matches the emailed link token or the 6-digit verification OTP (not expired)."""
    submitted = (submitted or "").strip()
    if not submitted:
        return False
    if user.verification_token and submitted == user.verification_token:
        exp = _expiry_utc(user.verification_token_expiry)
        if exp and now > exp:
            return False
        return True
    digits = "".join(c for c in submitted if c.isdigit())
    if len(digits) >= 6 and user.verification_otp and digits[:6] == (user.verification_otp or "")[:6]:
        exp = _expiry_utc(user.verification_otp_expiry) or _expiry_utc(user.verification_token_expiry)
        if exp and now > exp:
            return False
        return True
    return False


def _clear_email_verification_fields(user: User) -> None:
    user.verification_token = None
    user.verification_token_expiry = None
    user.verification_otp = None
    user.verification_otp_expiry = None


def _user_auth_payload(user: User) -> dict:
    """JWT companion profile returned on login / me / firebase."""
    return UserOut.model_validate(user).model_dump()


def _apply_trust_after_email_verify(user: User) -> None:
    """Tenants can use the product immediately after OTP/email verify; landlords/agents await KYC + admin."""
    if user.role == UserRole.tenant:
        user.trusted_for_commerce = True


class RefreshRequest(BaseModel):
    refresh_token: str


# ── REGISTER (step 1) ─────────────────────────────────────────────
def _send_registration_email(
    email: str,
    full_name: str,
    token: str,
    otp: str,
) -> None:
    sent = send_registration_verification_link(
        email,
        full_name,
        token,
        api_base_url=settings.api_public_base_url,
        otp=otp,
    )
    if not sent:
        print(f"[WARN] Could not send verification email to {email}. Token: {token}  OTP: {otp}")


@router.post("/register", status_code=201)
def register(
    payload: UserRegister,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if payload.role in (
        UserRole.system_admin,
        UserRole.gov_nira,
        UserRole.gov_kcca,
        UserRole.gov_ura,
    ) or str(payload.role).startswith("gov_"):
        raise HTTPException(
            status_code=403,
            detail="System administrator and government accounts cannot self-register.",
        )
    # Check duplicate
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "An account with this email already exists.")

    token = generate_verification_token()
    otp = generate_otp()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)

    user = auth_service.create_user(
        db, payload, verification_token=token, token_expiry=expiry, verification_otp=otp
    )

    background_tasks.add_task(
        _send_registration_email,
        user.email,
        user.full_name,
        token,
        otp,
    )

    body = {
        "message": "Account created. Check your email for a 6-digit code and verification link.",
        "email": user.email,
        "email_sent": None,
    }
    if settings.environment == "development":
        body["dev_verification_otp"] = otp
    return body


# ── VERIFY EMAIL via Link (GET request for email links) ────────────
@router.get("/verify-email")
def verify_email_link(email: str, token: str, db: Session = Depends(get_db)):
    """Verify email via link click. Redirects to frontend with success/error message."""
    from fastapi.responses import RedirectResponse
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return RedirectResponse(url=_login_redirect(error="account_not_found"))

    if user.email_verified:
        return RedirectResponse(url=_login_redirect(message="already_verified"))

    now = datetime.now(timezone.utc)
    if not _email_verification_secret_accepted(user, token, now):
        exp = _expiry_utc(user.verification_token_expiry) or _expiry_utc(user.verification_otp_expiry)
        if (user.verification_token or user.verification_otp) and exp and now > exp:
            return RedirectResponse(url=_login_redirect(error="token_expired"))
        return RedirectResponse(url=_login_redirect(error="invalid_token"))

    user.email_verified = True
    _clear_email_verification_fields(user)
    _apply_trust_after_email_verify(user)
    db.commit()

    return RedirectResponse(url=_login_redirect(verified="true", email=email))


@router.post("/verify-email", status_code=200)
def verify_email_token(payload: VerifyEmailTokenBody, db: Session = Depends(get_db)):
    """Same checks as the email link (GET), but returns JSON for SPA flows."""
    user = db.query(User).filter(User.email == str(payload.email)).first()
    if not user:
        raise error_response("Account not found.", status_code=404)
    if user.email_verified:
        return success_response(message="Email was already verified.")
    now = datetime.now(timezone.utc)
    if not _email_verification_secret_accepted(user, payload.token, now):
        exp = _expiry_utc(user.verification_token_expiry) or _expiry_utc(user.verification_otp_expiry)
        if (user.verification_token or user.verification_otp) and exp and now > exp:
            raise error_response("Verification code has expired. Register again or request a new email.", status_code=400)
        raise error_response("Invalid verification code or link token.", status_code=400)
    user.email_verified = True
    _clear_email_verification_fields(user)
    _apply_trust_after_email_verify(user)
    db.commit()
    return success_response(message="Email verified. You can sign in.")


# ── LOGIN ─────────────────────────────────────────────────────────
@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, payload.email, payload.password)
    if not user:
        raise error_response("Invalid email or password.", status_code=401)
    if is_government_officer(user.role):
        portal = settings.government_portal_path
        raise error_response(
            f"Government officers must sign in at the secure government portal ({portal}), not public login.",
            status_code=403,
        )
    if not user.is_active:
        raise error_response("Account is disabled. Contact support.", status_code=403)
    if not user.email_verified:
        raise error_response("Please verify your email before logging in.", status_code=403)

    tokens = auth_service.create_tokens(db, user)
    payload_out = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": tokens.get("token_type", "bearer"),
        "user": _user_auth_payload(user),
        "needs_government_2fa": is_government_officer(user.role),
    }
    return success_response(data=payload_out)


# ── REFRESH ───────────────────────────────────────────────────────
@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Accept refresh_token in request body (matches frontend client.js)."""
    token = payload.refresh_token
    decoded = decode_token(token)
    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    user_id = decoded.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    # Verify token matches stored refresh token
    if user.refresh_token != token:
        raise HTTPException(status_code=401, detail="Refresh token revoked.")

    tokens = auth_service.create_tokens(db, user)
    return tokens


# ── LOGOUT ────────────────────────────────────────────────────────
@router.post("/logout")
def logout(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.refresh_token = None
    db.commit()
    return {"message": "Logged out."}


# ── FORGOT PASSWORD ───────────────────────────────────────────────
@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Always return success to prevent email enumeration
    if not user:
        if settings.environment == "development":
            print(
                f"\n[INFO] forgot-password: no account for {payload.email!r} — "
                "no email sent. Register first or use the exact email on your account.\n"
            )
        return {"message": "If that email exists, a reset code has been sent."}

    otp = generate_otp()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    user.reset_otp = otp
    user.reset_otp_expiry = expiry
    db.commit()

    sent = send_password_reset_otp(user.email, otp)
    if not sent:
        print(
            f"\n[WARN] Password reset email was NOT sent (check SMTP in .env).\n"
            f"       Email: {user.email}\n"
            f"       Reset code (valid 15 min): {otp}\n"
        )
        if settings.environment == "development":
            return {
                "message": "Reset code generated. Email was not sent — configure SMTP in .env or use the dev code below.",
                "dev_reset_otp": otp,
                "email_sent": False,
            }

    return {"message": "If that email exists, a reset code has been sent.", "email_sent": True}


# ── RESET PASSWORD ────────────────────────────────────────────────
@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(404, "Account not found.")

    if not user.reset_otp or user.reset_otp != payload.otp:
        raise HTTPException(400, "Invalid or expired reset code.")

    expiry = user.reset_otp_expiry
    if expiry:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expiry:
            raise HTTPException(400, "Reset code has expired. Request a new one.")

    auth_service.set_password(db, user, payload.new_password)
    user.reset_otp = None
    user.reset_otp_expiry = None
    db.commit()

    return {"message": "Password reset successfully. You can now log in."}


@router.post("/firebase", summary="Exchange Firebase ID token for API JWT (optional)")
def firebase_sign_in(body: FirebaseSignInBody, db: Session = Depends(get_db)):
    claims = verify_firebase_id_token(body.id_token)
    if claims is None:
        raise HTTPException(
            status_code=503,
            detail="Firebase verification is not configured or the token is invalid.",
        )
    email = (claims.get("email") or "").strip().lower()
    uid = claims.get("sub") or claims.get("user_id")
    if not email:
        raise error_response("Firebase token did not include an email address.", status_code=400)

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise error_response(
            "No API account exists for this email. Register on the web first, then sign in with Firebase.",
            status_code=404,
        )
    if not user.is_active:
        raise error_response("Account is disabled. Contact support.", status_code=403)
    if is_government_officer(user.role) or is_system_admin(user.role):
        raise error_response(
            "Government and system administrator accounts cannot use social sign-in.",
            status_code=403,
        )

    if claims.get("email_verified") is True:
        user.email_verified = True
        _apply_trust_after_email_verify(user)

    if uid and not user.firebase_uid:
        user.firebase_uid = str(uid)[:128]
    db.commit()
    db.refresh(user)

    tokens = auth_service.create_tokens(db, user)
    return success_response(
        data={
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": tokens.get("token_type", "bearer"),
            "user": _user_auth_payload(user),
            "needs_government_2fa": is_government_officer(user.role),
        }
    )


# ── ME ────────────────────────────────────────────────────────────
@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return success_response(data=_user_auth_payload(current_user))