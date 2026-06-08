"""Property listing identity — Sui object/NFT minted when a landlord lists a property."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.property import Property
from app.models.user import User
from app.services.blockchain import blockchain_service, sui_move, walrus_service
from app.services.blockchain.wallet_provision import derive_keypair
from app.services import verification_service
from app.services.public_url_service import frontend_base_url
from app.utils.response import error_response

logger = logging.getLogger(__name__)

DEMO_LINE = (
    "Every property listing receives a verifiable on-chain identity on Sui, "
    "helping reduce fraud and duplicate listings."
)


def location_fingerprint(*, address: str, parish: Optional[str], district: Optional[str]) -> str:
    parts = [
        (address or "").strip().lower(),
        (parish or "").strip().lower(),
        (district or "Kampala").strip().lower(),
    ]
    normalized = "|".join(parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def location_label(prop: Property) -> str:
    bits = [prop.address]
    if prop.parish:
        bits.append(prop.parish)
    if prop.district:
        bits.append(prop.district)
    return ", ".join(bits)


def find_duplicate_listing(db: Session, fingerprint: str, *, exclude_id: Optional[int] = None) -> Optional[Property]:
    q = db.query(Property).filter(
        Property.sui_identity_hash == fingerprint,
        Property.is_active == True,  # noqa: E712
    )
    if exclude_id is not None:
        q = q.filter(Property.id != exclude_id)
    return q.first()


def _listing_payload(prop: Property, *, landlord_wallet: str, listed_at_ms: int, fingerprint: str) -> dict[str, Any]:
    return {
        "artifact_type": "property_listing_identity",
        "platform": "RentDirect UG",
        "property_id": prop.id,
        "landlord_wallet": landlord_wallet,
        "location": {
            "address": prop.address,
            "parish": prop.parish,
            "district": prop.district,
            "label": location_label(prop),
        },
        "listed_at_ms": listed_at_ms,
        "listed_at": datetime.fromtimestamp(listed_at_ms / 1000, tz=timezone.utc).isoformat(),
        "identity_hash": fingerprint,
        "tagline": (
            "Every property listing receives a verifiable on-chain identity on Sui, "
            "alongside KCCA government compliance review."
        ),
    }


def _explorer_tx_url(digest: Optional[str]) -> Optional[str]:
    if not (digest or "").strip():
        return None
    network = (settings.sui_network or "testnet").lower()
    return f"https://suiscan.xyz/{network}/tx/{digest.strip()}"


def _explorer_object_url(object_id: Optional[str]) -> Optional[str]:
    if not (object_id or "").strip():
        return None
    network = (settings.sui_network or "testnet").lower()
    return f"https://suiscan.xyz/{network}/object/{object_id.strip()}"


def identity_public_fields(prop: Property) -> dict[str, Any]:
    token = getattr(prop, "verification_token", None)
    return {
        "sui_identity_hash": getattr(prop, "sui_identity_hash", None),
        "sui_identity_object_id": getattr(prop, "sui_identity_object_id", None),
        "sui_identity_tx_digest": getattr(prop, "sui_identity_tx_digest", None),
        "sui_listed_at_ms": getattr(prop, "sui_listed_at_ms", None),
        "sui_identity_status": _identity_status(prop),
        "sui_identity_explorer_url": _explorer_object_url(getattr(prop, "sui_identity_object_id", None))
        or _explorer_tx_url(getattr(prop, "sui_identity_tx_digest", None)),
        "sui_identity_verify_url": f"{frontend_base_url()}/verify/property/{token}" if token else None,
        "sui_identity_tagline": (
            "Every property listing receives a verifiable on-chain identity on Sui, "
            "alongside KCCA government compliance review."
        ),
    }


def _identity_status(prop: Property) -> str:
    if getattr(prop, "sui_identity_object_id", None):
        return "minted"
    if getattr(prop, "sui_identity_tx_digest", None):
        return "anchored"
    if getattr(prop, "sui_identity_hash", None):
        return "registered"
    return "pending"


def ensure_listing_identity_if_missing(db: Session, prop: Property) -> None:
    """Backfill Sui listing identity for properties created before this feature shipped."""
    if (getattr(prop, "sui_identity_hash", None) or "").strip():
        return
    owner = prop.owner if getattr(prop, "owner", None) else db.query(User).filter(User.id == prop.owner_id).first()
    if not owner:
        return
    try:
        anchor_listing_identity(db, prop, owner)
        db.commit()
        db.refresh(prop)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Backfill listing identity failed for property %s: %s", prop.id, exc)


def anchor_listing_identity(db: Session, prop: Property, owner: User) -> dict[str, Any]:
    """
    Register listing identity when a property is created.
    Mints a Sui object when package + gas are available; always stores hash + manifest.
    """
    fingerprint = location_fingerprint(
        address=prop.address,
        parish=prop.parish,
        district=prop.district,
    )
    duplicate = find_duplicate_listing(db, fingerprint, exclude_id=prop.id)
    if duplicate:
        raise error_response(
            "A property listing already exists for this location on RentDirect. "
            "Duplicate listings are blocked to reduce fraud.",
            status_code=409,
        )

    wallet = blockchain_service.ensure_platform_wallet(db, owner, request_faucet=False)
    landlord_wallet = wallet.get("sui_address") or ""
    listed_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    payload = _listing_payload(
        prop,
        landlord_wallet=landlord_wallet,
        listed_at_ms=listed_at_ms,
        fingerprint=fingerprint,
    )

    try:
        stored = walrus_service.store_json(payload)
        if stored.content_hash:
            fingerprint = stored.content_hash
    except Exception as exc:  # noqa: BLE001
        logger.warning("Property listing Walrus manifest failed: %s", exc)

    prop.sui_identity_hash = fingerprint
    prop.sui_listed_at_ms = listed_at_ms
    verification_service.ensure_property_verify_token(prop)

    tx_digest: Optional[str] = None
    object_id: Optional[str] = None
    package_id = (settings.sui_package_id or "").strip()
    module = (getattr(settings, "sui_property_module", None) or "property_identity").strip()

    if package_id and landlord_wallet.startswith("0x"):
        try:
            sk, sender = derive_keypair(owner.id)
            tx_digest, object_id = sui_move.mint_property_listing_identity(
                sk,
                sender=sender,
                package_id=package_id,
                module=module,
                property_id=prop.id,
                location=location_label(prop).encode("utf-8"),
                listed_at_ms=listed_at_ms,
                recipient=landlord_wallet,
            )
            prop.sui_identity_tx_digest = tx_digest
            prop.sui_identity_object_id = object_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("On-chain property listing identity mint failed (property %s): %s", prop.id, exc)

    db.flush()
    return identity_public_fields(prop)
