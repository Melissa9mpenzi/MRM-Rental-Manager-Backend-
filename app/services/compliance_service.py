"""Government compliance badges and marketplace eligibility (NIRA → KCCA → URA)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.lease import Lease
from app.models.payment import Payment, PaymentType
from app.models.property import Property, Unit
from app.models.user import User, UserRole


GOVERNMENT_OFFICER_ROLE_VALUES = frozenset(
    r.value for r in (UserRole.gov_nira, UserRole.gov_kcca, UserRole.gov_ura, UserRole.system_admin)
)


def is_user_gov_suspended(user: User) -> bool:
    return bool(getattr(user, "gov_suspended", False))


def is_nira_verified_landlord(user: User | None) -> bool:
    if not user:
        return False
    if is_user_gov_suspended(user):
        return False
    return (user.kyc_review_status or "").lower() == "approved"


def is_kcca_approved_property(prop: Property | None) -> bool:
    if not prop:
        return False
    return (prop.gov_verification_status or "").lower() == "verified"


def property_has_recorded_rent(db: Session, property_id: int) -> bool:
    """True when at least one rent payment exists for units on this property."""
    base = [Payment.is_deleted.is_(False), Payment.payment_type == PaymentType.rent]

    via_unit = (
        db.query(Payment.id)
        .join(Unit, Payment.unit_id == Unit.id)
        .filter(Unit.property_id == property_id, *base)
        .first()
    )
    if via_unit:
        return True

    return (
        db.query(Payment.id)
        .join(Lease, Payment.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .filter(Unit.property_id == property_id, *base)
        .first()
        is not None
    )


def listing_compliance_badges(
    db: Session,
    *,
    owner: User | None,
    prop: Property,
) -> dict[str, bool]:
    nira = is_nira_verified_landlord(owner)
    kcca = is_kcca_approved_property(prop)
    ura = nira and kcca and property_has_recorded_rent(db, prop.id)
    return {
        "nira_verified_landlord": nira,
        "kcca_approved_property": kcca,
        "ura_compliant": ura,
        "marketplace_live": nira and kcca and bool(prop.is_active),
    }


def compliance_badges_public(badges: dict[str, bool]) -> dict[str, bool]:
    """Payload for marketplace / listing cards."""
    return {
        "nira_verified_landlord": bool(badges.get("nira_verified_landlord")),
        "kcca_approved_property": bool(badges.get("kcca_approved_property")),
        "ura_compliant": bool(badges.get("ura_compliant")),
    }
