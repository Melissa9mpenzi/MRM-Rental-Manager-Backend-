from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
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


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency for admin-only routes.
    Usage: current_user: User = Depends(require_admin)
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required."
        )
    return current_user


def require_landlord(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency for landlord-only routes.
    Usage: current_user: User = Depends(require_landlord)
    """
    if current_user.role != "landlord":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Landlord access required."
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
    if current_user.role not in ("admin", "staff", "landlord"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Staff access required."
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


def require_roles(allowed_roles: list):
    """
    Factory for multi-role dependencies.
    Usage: current_user: User = Depends(require_roles(["admin", "landlord"]))
    """
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return checker