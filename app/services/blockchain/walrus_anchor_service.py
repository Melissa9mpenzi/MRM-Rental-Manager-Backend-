"""Walrus proofs for KYC manifests, property packets, gov audit, and escrow — privacy-safe hashes."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.audit import AuditLog
from app.models.escrow_hold import EscrowHold
from app.models.lease import Lease
from app.models.property import Property
from app.models.user import User
from app.runtime import upload_root
from app.services.blockchain import walrus_service
from app.utils.kyc_media import kyc_user_dir

logger = logging.getLogger(__name__)

KYC_KINDS = ("id_front", "id_back", "selfie")


def proof_fields(
    blob_id: Optional[str],
    *,
    content_hash: Optional[str] = None,
    walrus_live: Optional[bool] = None,
) -> dict[str, Any]:
    bid = (blob_id or "").strip() or None
    if bid and bid.startswith("hash:"):
        content_hash = content_hash or bid[5:]
        bid = None
        walrus_live = False
    live = walrus_live if walrus_live is not None else bool(bid)
    return {
        "walrus_blob_id": bid,
        "walrus_url": walrus_service.public_url(bid),
        "content_hash": content_hash,
        "walrus_live": live,
        "storage_type": "walrus" if live else "content_hash",
    }


def _apply_store_result(target, result: walrus_service.WalrusStoreResult, *, blob_attr: str) -> dict[str, Any]:
    setattr(target, blob_attr, result.walrus_blob_id)
    if hasattr(target, "agreement_hash") and blob_attr == "walrus_blob_id":
        target.agreement_hash = result.content_hash
    return proof_fields(result.walrus_blob_id, content_hash=result.content_hash, walrus_live=result.walrus_live)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


def _safe_store_json(payload: dict[str, Any]) -> walrus_service.WalrusStoreResult:
    try:
        return walrus_service.store_json(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Walrus store_json failed: %s", exc)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        return walrus_service.WalrusStoreResult(content_hash=digest, walrus_blob_id=None, walrus_live=False)


def kyc_document_hashes(user_id: int) -> dict[str, Optional[str]]:
    base = kyc_user_dir(upload_root(), user_id)
    out: dict[str, Optional[str]] = {}
    for kind in KYC_KINDS:
        path = base / f"{kind}.jpg"
        out[kind] = _sha256_file(path)
    return out


def build_kyc_manifest(
    user: User,
    *,
    event: str = "submitted",
    officer_id: Optional[int] = None,
    decision: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    hashes = kyc_document_hashes(user.id)
    return {
        "artifact_type": "kyc_manifest",
        "platform": "RentDirect UG",
        "event": event,
        "user_id": user.id,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "national_id_number": getattr(user, "national_id_number", None),
        "kyc_review_status": user.kyc_review_status,
        "document_hashes": hashes,
        "privacy_note": "Raw ID images stay on platform storage; Walrus holds hash manifest only.",
        "officer_id": officer_id,
        "decision": decision,
        "note": note,
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }


def anchor_kyc_submission(db: Session, user: User) -> Optional[str]:
    if not kyc_document_hashes(user.id).get("id_front"):
        return getattr(user, "kyc_walrus_blob_id", None)
    payload = build_kyc_manifest(user, event="submitted")
    stored = _safe_store_json(payload)
    user.kyc_walrus_blob_id = stored.walrus_blob_id
    user.kyc_manifest_hash = stored.content_hash
    return stored.walrus_blob_id


def anchor_kyc_decision(
    db: Session,
    user: User,
    *,
    officer_id: int,
    decision: str,
    note: Optional[str] = None,
) -> Optional[str]:
    payload = build_kyc_manifest(
        user,
        event=f"nira_{decision}",
        officer_id=officer_id,
        decision=decision,
        note=note,
    )
    stored = _safe_store_json(payload)
    user.kyc_walrus_blob_id = stored.walrus_blob_id
    user.kyc_manifest_hash = stored.content_hash
    return stored.walrus_blob_id


def build_property_packet(
    prop: Property,
    *,
    event: str,
    officer_id: int,
    decision: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    photo_hash = None
    if prop.photo_path:
        p = str(prop.photo_path).replace("\\", "/")
        if "/uploads/" in p:
            rel = p.split("/uploads/", 1)[-1]
        else:
            rel = p.lstrip("/").removeprefix("uploads/")
        photo_path = Path(upload_root()) / rel
        photo_hash = _sha256_file(photo_path)

    return {
        "artifact_type": "property_verification",
        "platform": "RentDirect UG",
        "event": event,
        "property_id": prop.id,
        "name": prop.name,
        "address": prop.address,
        "district": prop.district,
        "owner_id": prop.owner_id,
        "gov_verification_status": prop.gov_verification_status,
        "photo_content_hash": photo_hash,
        "officer_id": officer_id,
        "decision": decision,
        "note": note,
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }


def anchor_property_decision(
    db: Session,
    prop: Property,
    *,
    officer_id: int,
    decision: str,
    note: Optional[str] = None,
) -> Optional[str]:
    payload = build_property_packet(
        prop,
        event=f"kcca_{decision}",
        officer_id=officer_id,
        decision=decision,
        note=note,
    )
    stored = _safe_store_json(payload)
    prop.gov_walrus_blob_id = stored.walrus_blob_id
    prop.gov_packet_hash = stored.content_hash
    return stored.walrus_blob_id


def build_audit_payload(log: AuditLog, actor_name: Optional[str] = None) -> dict[str, Any]:
    return {
        "artifact_type": "government_audit",
        "platform": "RentDirect UG",
        "audit_id": log.id,
        "officer_id": log.user_id,
        "officer_name": actor_name,
        "action": log.action,
        "table_name": log.table_name,
        "record_id": log.record_id,
        "details": log.new_value or log.old_value,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }


def anchor_audit_log(db: Session, log: AuditLog, *, actor_name: Optional[str] = None) -> None:
    payload = build_audit_payload(log, actor_name=actor_name)
    stored = _safe_store_json(payload)
    log.walrus_blob_id = stored.walrus_blob_id


def build_lease_agreement_payload(lease: Lease) -> dict[str, Any]:
    tenant = lease.tenant
    unit = lease.unit
    prop = unit.parent_property if unit else None
    return {
        "artifact_type": "rental_agreement",
        "platform": "RentDirect UG",
        "lease_id": lease.id,
        "tenant_id": lease.tenant_id,
        "owner_id": lease.owner_id,
        "unit_id": lease.unit_id,
        "property_name": prop.name if prop else None,
        "tenant_name": tenant.full_name if tenant else None,
        "start_date": lease.start_date.isoformat() if lease.start_date else None,
        "end_date": lease.end_date.isoformat() if lease.end_date else None,
        "monthly_rent_ugx": str(lease.monthly_rent),
        "deposit_amount_ugx": str(lease.deposit_amount or 0),
        "status": lease.status.value if hasattr(lease.status, "value") else str(lease.status),
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }


def anchor_lease_agreement(db: Session, lease: Lease) -> dict[str, Any]:
    """Walrus blob (when configured) + SHA-256 agreement hash — verifiable rental agreement."""
    from app.services import verification_service

    verification_service.ensure_lease_verify_token(lease)
    payload = build_lease_agreement_payload(lease)
    pre_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    stored = _safe_store_json({**payload, "agreement_hash": pre_hash})
    lease.agreement_hash = stored.content_hash
    lease.walrus_blob_id = stored.walrus_blob_id
    db.commit()
    from app.services.verification_service import verify_page_url

    return {
        "agreement_hash": stored.content_hash,
        "verification_token": lease.verification_token,
        "verification_url": verify_page_url(lease.verification_token),
        **proof_fields(stored.walrus_blob_id, content_hash=stored.content_hash, walrus_live=stored.walrus_live),
    }


def build_escrow_lease_payload(hold: EscrowHold, lease: Optional[Lease] = None) -> dict[str, Any]:
    return {
        "artifact_type": "escrow_lease",
        "platform": "RentDirect UG",
        "escrow_id": hold.id,
        "lease_id": hold.lease_id,
        "tenant_id": hold.tenant_id,
        "owner_id": hold.owner_id,
        "amount_ugx": str(hold.amount_ugx),
        "monthly_rent": str(lease.monthly_rent) if lease else None,
        "deposit_amount": str(lease.deposit_amount) if lease else None,
        "status": hold.status.value if hasattr(hold.status, "value") else str(hold.status),
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }


def anchor_escrow_lease(db: Session, hold: EscrowHold, lease: Optional[Lease] = None) -> Optional[str]:
    payload = build_escrow_lease_payload(hold, lease)
    stored = _safe_store_json(payload)
    hold.walrus_lease_blob_id = stored.walrus_blob_id
    return stored.walrus_blob_id


def build_escrow_release_payload(
    hold: EscrowHold,
    *,
    release_tx_digest: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "artifact_type": "escrow_release_proof",
        "platform": "RentDirect UG",
        "escrow_id": hold.id,
        "lease_id": hold.lease_id,
        "amount_ugx": str(hold.amount_ugx),
        "status": "released",
        "fund_tx_digest": hold.fund_tx_digest,
        "release_tx_digest": release_tx_digest or hold.release_tx_digest,
        "lease_walrus_blob_id": hold.walrus_lease_blob_id,
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }


def anchor_escrow_release(
    db: Session,
    hold: EscrowHold,
    *,
    release_tx_digest: Optional[str] = None,
) -> Optional[str]:
    payload = build_escrow_release_payload(hold, release_tx_digest=release_tx_digest)
    stored = _safe_store_json(payload)
    hold.walrus_release_blob_id = stored.walrus_blob_id
    return stored.walrus_blob_id


def export_gov_audit_bundle(
    db: Session,
    *,
    agency: str = "all",
    limit: int = 100,
    officer_id: Optional[int] = None,
) -> dict[str, Any]:
    from app.services import government_service

    entries = government_service.audit_trail(db, agency=agency, limit=limit)
    payload = {
        "artifact_type": "government_audit_export",
        "platform": "RentDirect UG",
        "agency": agency,
        "entry_count": len(entries),
        "exported_by_officer_id": officer_id,
        "entries": entries,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    stored = _safe_store_json(payload)
    return {
        "walrus_blob_id": stored.walrus_blob_id,
        "content_hash": stored.content_hash,
        **proof_fields(
            stored.walrus_blob_id,
            content_hash=stored.content_hash,
            walrus_live=stored.walrus_live,
        ),
        "entry_count": len(entries),
    }


def walrus_inventory(db: Session) -> dict[str, Any]:
    from app.models.blockchain_receipt import BlockchainReceipt

    kyc_count = (
        db.query(func.count(User.id)).filter(User.kyc_walrus_blob_id.isnot(None)).scalar() or 0
    )
    prop_count = (
        db.query(func.count(Property.id))
        .filter(Property.gov_walrus_blob_id.isnot(None))
        .scalar()
        or 0
    )
    audit_count = (
        db.query(func.count(AuditLog.id)).filter(AuditLog.walrus_blob_id.isnot(None)).scalar() or 0
    )
    receipt_count = (
        db.query(func.count(BlockchainReceipt.id))
        .filter(BlockchainReceipt.walrus_blob_id.isnot(None))
        .scalar()
        or 0
    )
    escrow_lease = (
        db.query(func.count(EscrowHold.id))
        .filter(EscrowHold.walrus_lease_blob_id.isnot(None))
        .scalar()
        or 0
    )
    escrow_release = (
        db.query(func.count(EscrowHold.id))
        .filter(EscrowHold.walrus_release_blob_id.isnot(None))
        .scalar()
        or 0
    )
    return {
        "walrus_configured": walrus_service.is_walrus_configured(),
        "network": (settings.sui_network or "testnet").lower(),
        "counts": {
            "kyc_manifests": int(kyc_count),
            "property_packets": int(prop_count),
            "audit_entries": int(audit_count),
            "payment_receipts": int(receipt_count),
            "escrow_lease_proofs": int(escrow_lease),
            "escrow_release_proofs": int(escrow_release),
        },
        "use_cases": list(KYC_KINDS),
    }
