"""Trust score and verification badges for Rental Hub."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User, UserRole


def compute_trust_score(user: User | None) -> int:
    if not user:
        return 0
    score = 40
    if user.email_verified:
        score += 10
    if (user.kyc_review_status or "").lower() == "approved":
        score += 25
    if user.trusted_for_commerce:
        score += 20
    if user.is_active:
        score += 5
    return min(100, score)


def user_badges(user: User | None, property_gov_status: str | None = None) -> list[str]:
    badges: list[str] = []
    if not user:
        return badges
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if user.trusted_for_commerce:
        if role == UserRole.landlord.value:
            badges.append("verified_landlord")
        elif role == UserRole.tenant.value:
            badges.append("trusted_tenant")
    if (user.kyc_review_status or "").lower() == "approved":
        badges.append("identity_verified")
    if role in {UserRole.gov_nira.value, UserRole.gov_kcca.value, UserRole.gov_ura.value}:
        badges.append("government")
    if role == UserRole.system_admin.value:
        badges.append("platform_admin")
    if property_gov_status == "verified":
        badges.append("gov_verified_property")
    return badges


def peer_profile(db: Session, user_id: int, property_gov_status: str | None = None) -> dict[str, Any]:
    u = db.query(User).filter(User.id == user_id).first()
    role = u.role.value if u and hasattr(u.role, "value") else None
    return {
        "id": user_id,
        "name": u.full_name if u else "User",
        "role": role,
        "trust_score": compute_trust_score(u),
        "badges": user_badges(u, property_gov_status),
    }
