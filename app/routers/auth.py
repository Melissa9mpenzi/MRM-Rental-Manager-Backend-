from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
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
) -> bool:
    sent = send_registration_verification_link(
        email,
        full_name,
        token,
        api_base_url=settings.api_public_base_url,
        otp=otp,
    )
    if not sent:
        print(
            f"\n[WARN] Verification email was NOT sent (configure SMTP_* on the API host).\n"
            f"       Email: {email}\n"
            f"       Code (valid 15 min): {otp}\n"
        )
    return sent


def _issue_verification_codes(user, db: Session) -> tuple[str, str]:
    """Refresh link token + 6-digit OTP (15 minutes)."""
    token = generate_verification_token()
    otp = generate_otp()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    user.verification_token = token
    user.verification_token_expiry = expiry
    user.verification_otp = otp
    user.verification_otp_expiry = expiry
    db.commit()
    db.refresh(user)
    return token, otp


def _registration_response_body(user, otp: str, email_sent: bool) -> dict:
    body = {
        "message": (
            "Account created. Check your email for a 6-digit code."
            if email_sent
            else "Account created. We could not send email — use Resend code or the one-time code shown below."
        ),
        "email": user.email,
        "email_sent": email_sent,
    }
    if not email_sent:
        body["verification_otp_fallback"] = otp
    elif settings.environment == "development":
        body["dev_verification_otp"] = otp
    return body


class ResendVerificationRequest(BaseModel):
    email: EmailStr


@router.post("/register", status_code=201)
def register(
    payload: UserRegister,
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

    email_sent = _send_registration_email(user.email, user.full_name, token, otp)
    return _registration_response_body(user, otp, email_sent)


@router.post("/resend-verification")
def resend_verification(payload: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Send a fresh 6-digit code (agent, landlord, tenant signup)."""
    user = db.query(User).filter(User.email == str(payload.email)).first()
    if not user:
        return {
            "message": "If that email is registered and not yet verified, a new code has been sent.",
            "email_sent": None,
        }
    if user.email_verified:
        return {
            "message": "This email is already verified. You can sign in.",
            "email_verified": True,
            "email_sent": True,
        }

    token, otp = _issue_verification_codes(user, db)
    email_sent = _send_registration_email(user.email, user.full_name, token, otp)
    body = {
        "message": (
            "A new verification code was sent to your inbox."
            if email_sent
            else "Email could not be sent. Use the one-time code below or configure SMTP on the server."
        ),
        "email": user.email,
        "email_sent": email_sent,
    }
    if not email_sent:
        body["verification_otp_fallback"] = otp
    elif settings.environment == "development":
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
            raise error_response(
                "Verification code has expired. Use Resend code on the verify page or register again.",
                status_code=400,
            )
        raise error_response("Invalid verification code or link token.", status_code=400)
    user.email_verified = True
    _clear_email_verification_fields(user)
    _apply_trust_after_email_verify(user)
    db.commit()
    return success_response(message="Email verified. You can sign in.")


# ── LOGIN ─────────────────────────────────────────────────────────
@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    from sqlalchemy.exc import SQLAlchemyError

    from app.config import database_url_looks_configured

    if not database_url_looks_configured():
        raise error_response(
            "Server database is not configured. Set DATABASE_URL on the API host (Vercel → Environment Variables).",
            status_code=503,
        )
    try:
        user = auth_service.authenticate(db, payload.email, payload.password)
    except SQLAlchemyError as exc:
        from app.db_errors import database_error_response

        msg, code = database_error_response(exc)
        raise error_response(msg, status_code=code)
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

    try:
        tokens = auth_service.create_tokens(db, user)
    except SQLAlchemyError as exc:
        from app.db_errors import database_error_response

        msg, code = database_error_response(exc)
        raise error_response(msg, status_code=code)

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