from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Union
from datetime import datetime

from app.models.user import UserRole


class VerifyEmailTokenBody(BaseModel):
    """Verify signup email: paste the long link token or the 6-digit code from the registration email."""

    email: EmailStr
    token: str


class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    password: str
    role: UserRole = UserRole.tenant

    @field_validator("role", mode="before")
    @classmethod
    def register_role_aliases(cls, v: Union[str, UserRole, None]) -> Union[str, UserRole]:
        """Accept UI label 'agent' as staff (API enum). Default tenant (fastest onboarding)."""
        if v is None:
            return UserRole.tenant
        if isinstance(v, UserRole):
            return v
        s = str(v).strip().lower()
        if not s:
            return UserRole.tenant
        if s == "agent":
            return UserRole.staff
        if s == "system_admin":
            raise ValueError("System administrator accounts are created by platform operators only.")
        if s.startswith("gov_"):
            raise ValueError("Government officer accounts are provisioned by invitation only.")
        try:
            return UserRole(s)
        except ValueError as exc:
            raise ValueError("Invalid role. Choose landlord, tenant, or agent.") from exc

    @field_validator("password")
    @classmethod
    def password_length(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_length(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    phone: Optional[str] = None
    national_id_number: Optional[str] = None
    role: str
    is_active: bool
    email_verified: bool
    kyc_submitted_at: Optional[datetime] = None
    kyc_review_status: str = "none"
    kyc_walrus_blob_id: Optional[str] = None
    kyc_manifest_hash: Optional[str] = None
    trusted_for_commerce: bool = False
    firebase_uid: Optional[str] = None
    sui_address: Optional[str] = None
    sui_wallet_auto: bool = False
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FirebaseSignInBody(BaseModel):
    """Exchange a Firebase Auth ID token for an API session (JWT)."""

    id_token: str


class PrivySignInBody(BaseModel):
    """Exchange a Privy access token for an API session (JWT). Optional Sui address from embedded wallet."""

    access_token: str
    sui_address: Optional[str] = None
    role: Optional[UserRole] = UserRole.tenant


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut