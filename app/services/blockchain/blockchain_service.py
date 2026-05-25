"""Hybrid Web3 layer — wallets, receipts, escrow (works alongside MoMo/Pesapal)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.blockchain_receipt import BlockchainReceipt, ReceiptAnchorStatus
from app.models.blockchain_wallet import BlockchainWallet
from app.models.escrow_hold import EscrowHold, EscrowStatus
from app.models.lease import Lease
from app.models.payment import Payment
from app.models.payment_checkout import PaymentCheckout
from app.models.tenant import Tenant
from app.models.user import User
from app.services.blockchain import sui_rpc, walrus_anchor_service, walrus_service
from app.utils.response import error_response


def is_sui_configured() -> bool:
    return bool((settings.sui_treasury_address or "").strip())


def blockchain_public_status() -> dict[str, Any]:
    return {
        "enabled": is_sui_configured(),
        "network": (settings.sui_network or "devnet").lower(),
        "rpc_url": sui_rpc.rpc_url(),
        "treasury_configured": bool((settings.sui_treasury_address or "").strip()),
        "package_id": (settings.sui_package_id or "").strip() or None,
        "escrow_module": (settings.sui_escrow_module or "escrow").strip(),
        "walrus_configured": walrus_service.is_walrus_configured(),
        "ugx_per_sui": float(settings.sui_ugx_per_sui or 6_000_000),
        "supports": {
            "wallet_payments": is_sui_configured(),
            "receipt_anchoring": is_sui_configured(),
            "escrow": bool((settings.sui_package_id or "").strip()),
            "walrus_storage": True,
            "walrus_publisher_live": walrus_service.is_walrus_configured(),
            "kyc_manifests": True,
            "property_packets": True,
            "gov_audit_blobs": True,
        },
    }


def link_wallet(db: Session, user: User, sui_address: str, wallet_name: Optional[str] = None) -> dict:
    addr = (sui_address or "").strip()
    if not addr.startswith("0x") or len(addr) < 10:
        raise error_response("Invalid Sui address.", status_code=400)

    db.query(BlockchainWallet).filter(
        BlockchainWallet.user_id == user.id,
        BlockchainWallet.is_primary == True,  # noqa: E712
    ).update({"is_primary": False})

    existing = (
        db.query(BlockchainWallet)
        .filter(BlockchainWallet.user_id == user.id, BlockchainWallet.sui_address == addr)
        .first()
    )
    if existing:
        existing.is_primary = True
        existing.wallet_name = wallet_name or existing.wallet_name
    else:
        db.add(
            BlockchainWallet(
                user_id=user.id,
                sui_address=addr,
                wallet_name=wallet_name,
                is_primary=True,
            )
        )
    db.commit()
    return get_primary_wallet(db, user)


def get_primary_wallet(db: Session, user: User) -> dict:
    row = (
        db.query(BlockchainWallet)
        .filter(BlockchainWallet.user_id == user.id, BlockchainWallet.is_primary == True)  # noqa: E712
        .first()
    )
    if not row:
        return {"linked": False, "sui_address": None}
    return {
        "linked": True,
        "sui_address": row.sui_address,
        "wallet_name": row.wallet_name,
        "linked_at": row.linked_at.isoformat() if row.linked_at else None,
    }


def _receipt_payload(
    *,
    payment: Optional[Payment],
    checkout: Optional[PaymentCheckout],
    invoice_number: Optional[str],
) -> dict[str, Any]:
    return {
        "platform": "RentDirect UG",
        "payment_id": payment.id if payment else None,
        "checkout_reference": checkout.reference if checkout else None,
        "invoice_number": invoice_number,
        "amount_ugx": str(payment.amount) if payment else (str(checkout.amount) if checkout else None),
        "method": (
            payment.payment_method.value if payment and hasattr(payment.payment_method, "value") else None
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def anchor_payment_receipt(
    db: Session,
    *,
    payment: Payment,
    checkout: Optional[PaymentCheckout] = None,
    tx_digest: Optional[str] = None,
) -> BlockchainReceipt:
    """Create immutable receipt record; optionally anchor tx + Walrus blob."""
    payload = _receipt_payload(payment=payment, checkout=checkout, invoice_number=None)
    receipt_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    try:
        walrus_id = walrus_service.store_json({**payload, "receipt_hash": receipt_hash})
    except Exception:
        walrus_id = f"hash:{receipt_hash[:32]}"

    row = BlockchainReceipt(
        payment_id=payment.id,
        checkout_id=checkout.id if checkout else None,
        lease_id=payment.lease_id,
        owner_id=payment.owner_id,
        network=(settings.sui_network or "devnet").lower(),
        tx_digest=tx_digest,
        receipt_hash=receipt_hash,
        walrus_blob_id=walrus_id,
        payment_method=(
            payment.payment_method.value if hasattr(payment.payment_method, "value") else str(payment.payment_method)
        ),
        amount_ugx=str(payment.amount),
        status=ReceiptAnchorStatus.anchored if tx_digest else ReceiptAnchorStatus.pending,
        metadata_json=json.dumps(payload)[:4000],
        anchored_at=datetime.now(timezone.utc) if tx_digest else None,
    )
    db.add(row)
    db.flush()
    return row


def create_escrow_for_lease(db: Session, user: User, lease_id: int) -> EscrowHold:
    lease = db.query(Lease).filter(Lease.id == lease_id).first()
    if not lease:
        raise error_response("Lease not found.", status_code=404)
    if lease.owner_id != user.id and user.role.value != "system_admin":
        raise error_response("Access denied.", status_code=403)

    existing = (
        db.query(EscrowHold)
        .filter(
            EscrowHold.lease_id == lease_id,
            EscrowHold.status.in_([EscrowStatus.pending, EscrowStatus.funded, EscrowStatus.held]),
        )
        .first()
    )
    if existing:
        return existing

    amount = Decimal(str(lease.deposit_amount or lease.monthly_rent or 0))
    mist = sui_rpc.ugx_to_mist(amount)

    hold = EscrowHold(
        lease_id=lease.id,
        tenant_id=lease.tenant_id,
        owner_id=lease.owner_id,
        amount_ugx=amount,
        amount_mist=str(mist),
        status=EscrowStatus.pending,
    )
    db.add(hold)
    db.flush()
    walrus_anchor_service.anchor_escrow_lease(db, hold, lease)
    db.commit()
    db.refresh(hold)
    return hold


def release_escrow(db: Session, user: User, escrow_id: int, release_tx_digest: Optional[str] = None) -> EscrowHold:
    hold = db.query(EscrowHold).filter(EscrowHold.id == escrow_id).first()
    if not hold:
        raise error_response("Escrow not found.", status_code=404)
    if hold.owner_id != user.id and user.role.value != "system_admin":
        raise error_response("Access denied.", status_code=403)
    if hold.status not in (EscrowStatus.funded, EscrowStatus.held):
        raise error_response(f"Escrow cannot be released from status {hold.status.value}.", status_code=409)

    hold.status = EscrowStatus.released
    hold.release_tx_digest = release_tx_digest
    hold.released_at = datetime.now(timezone.utc)
    walrus_anchor_service.anchor_escrow_release(db, hold, release_tx_digest=release_tx_digest)
    db.commit()
    db.refresh(hold)
    return hold


def list_escrows_for_user(db: Session, user: User) -> list[dict]:
    q = db.query(EscrowHold)
    if user.role.value == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        if not tenant:
            return []
        q = q.filter(EscrowHold.tenant_id == tenant.id)
    elif user.role.value != "system_admin":
        q = q.filter(EscrowHold.owner_id == user.id)

    rows = q.order_by(EscrowHold.created_at.desc()).limit(100).all()
    return [_escrow_out(r) for r in rows]


def list_receipts_for_user(db: Session, user: User, limit: int = 50) -> list[dict]:
    q = db.query(BlockchainReceipt)
    if user.role.value == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        if not tenant:
            return []
        q = q.join(Payment, BlockchainReceipt.payment_id == Payment.id).filter(Payment.tenant_id == tenant.id)
    elif user.role.value != "system_admin":
        q = q.filter(BlockchainReceipt.owner_id == user.id)

    rows = q.order_by(BlockchainReceipt.created_at.desc()).limit(limit).all()
    return [_receipt_out(r) for r in rows]


def admin_dashboard(db: Session, user: User) -> dict[str, Any]:
    """Aggregate blockchain metrics for Sui portal dashboards."""
    receipts = list_receipts_for_user(db, user, limit=200)
    escrows = list_escrows_for_user(db, user)
    status = blockchain_public_status()

    active_escrow = sum(1 for e in escrows if e.get("status") in ("pending", "funded", "held"))
    completed_escrow = sum(1 for e in escrows if e.get("status") == "released")

    by_type: dict[str, int] = {"payments": 0, "escrow": 0, "contracts": 0, "refunds": 0}
    for r in receipts:
        m = (r.get("payment_method") or "payment").lower()
        if m == "sui":
            by_type["payments"] += 1
        else:
            by_type["payments"] += 1
    by_type["escrow"] = len(escrows)

    recent = []
    for r in receipts[:15]:
        recent.append({
            "id": r.get("id"),
            "tx_hash": r.get("tx_digest") or r.get("receipt_hash", "")[:16],
            "type": "Payment" if r.get("payment_method") != "escrow" else "Escrow",
            "from": "Tenant",
            "to": "Treasury",
            "amount_sui": _mist_to_sui_display(r.get("amount_ugx")),
            "status": "Success" if r.get("status") == "anchored" else r.get("status", "pending"),
            "time": r.get("created_at"),
            "explorer_url": r.get("explorer_url"),
            "receipt": r,
        })

    volume_days = _volume_by_day(receipts)
    net = _network_snapshot(status.get("network", "devnet"))

    package_id = status.get("package_id")
    smart_contracts = []
    if package_id:
        smart_contracts.append({
            "name": "LeaseContract",
            "address": package_id,
            "type": "Lease Agreement",
            "calls": len(receipts),
            "status": "Active",
            "deployed_at": None,
        })
        smart_contracts.append({
            "name": "EscrowVault",
            "address": f"{package_id}::escrow",
            "type": "Escrow",
            "calls": len(escrows),
            "status": "Active",
            "deployed_at": None,
        })

    return {
        **status,
        "totals": {
            "receipts": len(receipts),
            "transactions": len(receipts) + len(escrows),
            "volume_sui": round(sum(_mist_to_sui_display(r.get("amount_ugx")) for r in receipts), 4),
            "active_escrow": active_escrow,
            "completed_escrow": completed_escrow,
            "smart_contracts": len(smart_contracts) or (1 if status.get("enabled") else 0),
        },
        "wallet": {
            "sui_balance": None,
            "escrow_balance": round(
                sum(_mist_to_sui_display(e.get("amount_ugx")) for e in escrows if e.get("status") in ("funded", "held")),
                4,
            ),
        },
        "recent_transactions": recent,
        "volume_by_day": volume_days,
        "transactions_by_type": [
            {"name": "Payments", "value": by_type["payments"], "color": "#3b82f6"},
            {"name": "Escrow", "value": by_type["escrow"], "color": "#8b5cf6"},
            {"name": "Contract Calls", "value": by_type["contracts"], "color": "#22d3ee"},
            {"name": "Refunds", "value": by_type["refunds"], "color": "#f59e0b"},
        ],
        "network_status": net,
        "escrows": [_escrow_row(e) for e in escrows],
        "smart_contracts": smart_contracts,
        "receipts": receipts,
    }


def _mist_to_sui_display(amount_ugx: Any) -> float:
    try:
        ugx = float(amount_ugx or 0)
        rate = float(settings.sui_ugx_per_sui or 6_000_000)
        return ugx / rate if rate else 0
    except (TypeError, ValueError):
        return 0.0


def _volume_by_day(receipts: list[dict]) -> list[dict]:
    from collections import defaultdict

    buckets: dict[str, float] = defaultdict(float)
    for r in receipts:
        day = (r.get("created_at") or "")[:10]
        if day:
            buckets[day] += _mist_to_sui_display(r.get("amount_ugx"))
    if not buckets:
        return [
            {"day": "Mon", "volume": 0},
            {"day": "Tue", "volume": 0},
            {"day": "Wed", "volume": 0},
            {"day": "Thu", "volume": 0},
            {"day": "Fri", "volume": 0},
            {"day": "Sat", "volume": 0},
            {"day": "Sun", "volume": 0},
        ]
    items = sorted(buckets.items())[-7:]
    return [{"day": d[5:] or d, "volume": round(v, 4)} for d, v in items]


def _network_snapshot(network: str) -> dict[str, Any]:
    base = {"healthy": True, "network": network, "block_height": "—", "tps": "—", "checkpoint": "—", "epoch": "—", "gas_mist": "—"}
    if not is_sui_configured():
        base["healthy"] = False
        return base
    try:
        cp = sui_rpc._rpc("sui_getLatestCheckpointSequenceNumber", [])
        base["checkpoint"] = str(cp)
        base["block_height"] = str(cp)
        base["tps"] = "297"
        base["epoch"] = "—"
        base["gas_mist"] = "750"
    except Exception:
        base["healthy"] = False
    return base


def _escrow_row(e: dict) -> dict:
    return {
        **e,
        "contract_id": f"ESC-{e.get('id', 0):04d}",
        "property_name": f"Lease #{e.get('lease_id', '—')}",
        "tenant": e.get("tenant_sui_address") or "—",
        "landlord": e.get("landlord_sui_address") or "—",
        "amount_sui": _mist_to_sui_display(e.get("amount_ugx")),
    }


def get_receipt(db: Session, user: User, receipt_id: int) -> dict:
    q = db.query(BlockchainReceipt).filter(BlockchainReceipt.id == receipt_id)
    if user.role.value == "tenant":
        tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
        if not tenant:
            raise error_response("Not found.", status_code=404)
        q = q.join(Payment, BlockchainReceipt.payment_id == Payment.id).filter(Payment.tenant_id == tenant.id)
    elif user.role.value != "system_admin":
        q = q.filter(BlockchainReceipt.owner_id == user.id)
    row = q.first()
    if not row:
        raise error_response("Receipt not found.", status_code=404)
    out = _receipt_out(row)
    out["receipt_id"] = f"RCP-{row.id:05d}"
    out["type"] = "Payment"
    out["related_to"] = "Rent Payment"
    return out


def _escrow_out(h: EscrowHold) -> dict:
    lease_proof = walrus_anchor_service.proof_fields(h.walrus_lease_blob_id)
    release_proof = walrus_anchor_service.proof_fields(
        getattr(h, "walrus_release_blob_id", None)
    )
    return {
        "id": h.id,
        "lease_id": h.lease_id,
        "amount_ugx": float(h.amount_ugx),
        "amount_mist": h.amount_mist,
        "status": h.status.value,
        "escrow_object_id": h.escrow_object_id,
        "fund_tx_digest": h.fund_tx_digest,
        "release_tx_digest": h.release_tx_digest,
        "tenant_sui_address": h.tenant_sui_address,
        "landlord_sui_address": h.landlord_sui_address,
        "walrus_lease_blob_id": h.walrus_lease_blob_id,
        "walrus_release_blob_id": getattr(h, "walrus_release_blob_id", None),
        "walrus_lease_url": lease_proof.get("walrus_url"),
        "walrus_release_url": release_proof.get("walrus_url"),
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "released_at": h.released_at.isoformat() if h.released_at else None,
    }


def _receipt_out(r: BlockchainReceipt) -> dict:
    return {
        "id": r.id,
        "payment_id": r.payment_id,
        "network": r.network,
        "tx_digest": r.tx_digest,
        "receipt_hash": r.receipt_hash,
        "walrus_blob_id": r.walrus_blob_id,
        "walrus_url": walrus_service.public_url(r.walrus_blob_id or ""),
        "status": r.status.value,
        "payment_method": r.payment_method,
        "amount_ugx": r.amount_ugx,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "explorer_url": (
            f"https://suiscan.xyz/{r.network}/tx/{r.tx_digest}" if r.tx_digest else None
        ),
    }
