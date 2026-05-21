from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    tenant = "tenant"
    staff = "staff"  # Agent in UI
    landlord = "landlord"
    # System operator — seed only, runs the entire platform (not a government officer)
    system_admin = "system_admin"
    # Government portal officers (invitation-only, web-only)
    gov_nira = "gov_nira"
    gov_kcca = "gov_kcca"
    gov_ura = "gov_ura"


GOVERNMENT_OFFICER_ROLES = frozenset(
    {UserRole.gov_nira, UserRole.gov_kcca, UserRole.gov_ura}
)

SYSTEM_ADMIN_ROLE = UserRole.system_admin


def is_government_officer(role) -> bool:
    val = role.value if hasattr(role, "value") else str(role)
    return val in {r.value for r in GOVERNMENT_OFFICER_ROLES}


def is_system_admin(role) -> bool:
    val = role.value if hasattr(role, "value") else str(role)
    return val == UserRole.system_admin.value


def can_access_government_portal(role) -> bool:
    return is_government_officer(role) or is_system_admin(role)


# Backward-compatible alias used across routers
def is_government_role(role) -> bool:
    return can_access_government_portal(role)


is_global_admin = is_system_admin
GLOBAL_ADMIN_ROLE = SYSTEM_ADMIN_ROLE


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    password_hash   = Column(String(255), nullable=False)
    full_name       = Column(String(150), nullable=False)
    phone           = Column(String(20), nullable=True)
    national_id_number = Column(String(20), nullable=True, index=True)
    role            = Column(Enum(UserRole), default=UserRole.tenant, nullable=False)
    is_active       = Column(Boolean, default=True)
    email_verified  = Column(Boolean, default=False)
    kyc_submitted_at = Column(DateTime, nullable=True)
    kyc_review_status = Column(String(20), nullable=False, default="none")
    trusted_for_commerce = Column(Boolean, nullable=False, default=False)
    firebase_uid = Column(String(128), nullable=True, unique=True, index=True)

    reset_otp       = Column(String(10), nullable=True)
    reset_otp_expiry = Column(DateTime, nullable=True)

    verification_token = Column(String(100), nullable=True)
    verification_token_expiry = Column(DateTime, nullable=True)
    verification_otp = Column(String(10), nullable=True)
    verification_otp_expiry = Column(DateTime, nullable=True)

    refresh_token   = Column(String(500), nullable=True)

    gov_agency = Column(String(24), nullable=True)
    gov_work_id = Column(String(64), nullable=True)
    gov_security_pin_hash = Column(String(255), nullable=True)
    gov_2fa_enabled = Column(Boolean, nullable=False, default=False)
    gov_onboarding_complete = Column(Boolean, nullable=False, default=False)

    last_login      = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, server_default=func.now())
    updated_at      = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<User id={self.id} email={self.email} role={self.role}>"
