from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    landlord = "landlord"
    staff = "staff"
    tenant = "tenant"


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    password_hash   = Column(String(255), nullable=False)
    full_name       = Column(String(150), nullable=False)
    phone           = Column(String(20), nullable=True)
    role            = Column(Enum(UserRole), default=UserRole.tenant, nullable=False)
    is_active       = Column(Boolean, default=True)
    email_verified  = Column(Boolean, default=False)
    kyc_submitted_at = Column(DateTime, nullable=True)
    # Trust / moderation (landlord & staff): listings & payments require admin approval after KYC.
    kyc_review_status = Column(String(20), nullable=False, default="none")  # none | pending | approved | rejected
    trusted_for_commerce = Column(Boolean, nullable=False, default=False)
    # Linked Firebase Auth UID (optional; used with POST /auth/firebase).
    firebase_uid = Column(String(128), nullable=True, unique=True, index=True)

    # Password reset — 6-digit OTP stored temporarily
    reset_otp       = Column(String(10), nullable=True)
    reset_otp_expiry = Column(DateTime, nullable=True)

    # Email verification token
    verification_token = Column(String(100), nullable=True)
    verification_token_expiry = Column(DateTime, nullable=True)
    # 6-digit OTP (same window as link) — emailed alongside the verify link
    verification_otp = Column(String(10), nullable=True)
    verification_otp_expiry = Column(DateTime, nullable=True)

    # Refresh token stored server-side for revocation
    refresh_token   = Column(String(500), nullable=True)

    last_login      = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, server_default=func.now())
    updated_at      = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<User id={self.id} email={self.email} role={self.role}>"