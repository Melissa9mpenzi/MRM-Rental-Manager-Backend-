from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import (
    User,
    UserRole,
    can_access_government_portal,
    is_government_officer,
    is_system_admin,
)
from app.utils.security import decode_token

# Use HTTPBearer — extracts "Authorization: Bearer <token>" header
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency for all protected routes.
    Validates the JWT access token and returns the current User.
    Usage: current_user: User = Depends(get_current_user)
    """
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity."
        )

    user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated."
        )

    return user


def require_system_admin(current_user: User = Depends(get_current_user)) -> User:
    """System administrator — seed-only operator for the entire platform."""
    if not is_system_admin(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System administrator access required.",
        )
    return current_user


require_global_admin = require_system_admin
require_admin = require_system_admin


def require_landlord(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency for landlord-only routes.
    Usage: current_user: User = Depends(require_landlord)
    """
    if _role_str(current_user) != UserRole.landlord.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Landlord access required.",
        )
    return current_user


def require_staff(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency for staff-only routes.
    Usage: current_user: User = Depends(require_staff)
    """
    if current_user.role != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required."
        )
    return current_user


def require_tenant(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency for tenant-only routes.
    Usage: current_user: User = Depends(require_tenant)
    """
    if current_user.role != "tenant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access required."
        )
    return current_user


def require_admin_or_staff(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency for admin or staff routes (property management).
    Usage: current_user: User = Depends(require_admin_or_staff)
    """
    if current_user.role not in (
        UserRole.system_admin.value,
        UserRole.staff.value,
        UserRole.landlord.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff or landlord access required."
        )
    return current_user


def require_trusted_for_listings(current_user: User = Depends(get_current_user)) -> User:
    """
    Landlords and agents (staff) must be admin-approved (trusted_for_commerce) before
    publishing listings or other high-risk landlord actions.
    """
    if str(current_user.role) in ("landlord", "staff"):
        trusted = getattr(current_user, "trusted_for_commerce", True)
        if not trusted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "message": "Your landlord or agent account is not yet approved to publish listings. "
                    "Complete KYC and wait for admin review, or contact support.",
                },
            )
    return current_user


def _role_str(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def require_government(current_user: User = Depends(get_current_user)) -> User:
    """Government officers or system administrator (portal oversight)."""
    if not can_access_government_portal(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Government portal access required.",
        )
    return current_user


def require_government_agency(agency: str):
    """
    agency: nira | kcca | ura | all
    System administrator may access all agencies.
    """
    agency = agency.lower()

    def checker(current_user: User = Depends(get_current_user)) -> User:
        role = _role_str(current_user)
        if role == UserRole.system_admin.value:
            return current_user
        if agency == "nira" and role == UserRole.gov_nira.value:
            return current_user
        if agency == "kcca" and role == UserRole.gov_kcca.value:
            return current_user
        if agency == "ura" and role == UserRole.gov_ura.value:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied for {agency.upper()} module.",
        )

    return checker


def require_roles(allowed_roles: list):
    """
    Factory for multi-role dependencies.
    Usage: current_user: User = Depends(require_roles(["system_admin", "landlord"]))
    """
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return checker