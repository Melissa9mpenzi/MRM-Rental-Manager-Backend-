"""Portable wallet reputation from on-chain rental activity."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.blockchain_receipt import BlockchainReceipt, ReceiptAnchorStatus
from app.models.blockchain_wallet import BlockchainWallet
from app.models.lease import Lease
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import User


def _wallet_address(db: Session, user_id: int) -> str | None:
    row = (
        db.query(BlockchainWallet)
        .filter(
            BlockchainWallet.user_id == user_id,
            BlockchainWallet.is_primary == True,  # noqa: E712
        )
        .first()
    )
    return (row.sui_address or "").strip() or None if row else None


def _reputation_level(score: int) -> str:
    if score >= 80:
        return "established"
    if score >= 45:
        return "trusted"
    if score >= 15:
        return "building"
    return "new"


def compute_wallet_reputation(db: Session, user: User) -> dict[str, Any]:
    """
    Derive reputation from verifiable Sui-linked activity (no separate fake score table).
    Updates automatically as listings, leases, and payments anchor on-chain.
    """
    properties_verified = (
        db.query(Property)
        .filter(
            Property.owner_id == user.id,
            Property.is_active == True,  # noqa: E712
            Property.sui_identity_hash.isnot(None),
        )
        .count()
    )

    leases_anchored = (
        db.query(Lease)
        .filter(
            Lease.owner_id == user.id,
            Lease.agreement_hash.isnot(None),
        )
        .count()
    )

    tenant_row = db.query(Tenant).filter(Tenant.user_id == user.id).first()
    if tenant_row:
        leases_anchored += (
            db.query(Lease)
            .filter(
                Lease.tenant_id == tenant_row.id,
                Lease.agreement_hash.isnot(None),
            )
            .count()
        )

    on_chain_payments = (
        db.query(BlockchainReceipt)
        .filter(
            BlockchainReceipt.owner_id == user.id,
            BlockchainReceipt.tx_digest.isnot(None),
            BlockchainReceipt.status == ReceiptAnchorStatus.anchored,
        )
        .count()
    )

    if tenant_row:
        from app.models.payment import Payment

        on_chain_payments += (
            db.query(BlockchainReceipt)
            .join(Payment, BlockchainReceipt.payment_id == Payment.id)
            .filter(
                Payment.tenant_id == tenant_row.id,
                BlockchainReceipt.tx_digest.isnot(None),
            )
            .count()
        )

    score = (
        properties_verified * 12
        + leases_anchored * 18
        + on_chain_payments * 22
    )
    level = _reputation_level(score)

    return {
        "score": score,
        "level": level,
        "label": {
            "new": "New on-chain",
            "building": "Building trust",
            "trusted": "Trusted renter / landlord",
            "established": "Established on Sui",
        }.get(level, "New on-chain"),
        "stats": {
            "properties_on_sui": properties_verified,
            "agreements_anchored": leases_anchored,
            "on_chain_payments": on_chain_payments,
        },
        "sui_address": _wallet_address(db, user.id),
        "updates_when": [
            "Property listing identity registered on Sui",
            "Rental agreement hash anchored",
            "Rent payment confirmed on-chain",
        ],
    }
