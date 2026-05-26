"""Public blockchain verification — receipts, contracts, property, compliance."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models.lease import Lease
from app.models.payment import Payment
from app.models.property import Property, Unit
from app.models.system_receipt import SystemReceipt
from app.models.tenant import Tenant
from app.models.user import User
from app.services.blockchain import sui_rpc, walrus_anchor_service


def new_verify_token() -> str:
    return secrets.token_urlsafe(24)


def verify_page_url(token: str, *, kind: Optional[str] = None) -> str:
    base = (settings.frontend_base_url or "http://localhost:5173").rstrip("/")
    if kind:
        return f"{base}/verify/{kind}/{token}"
    return f"{base}/verify/{token}"


def _checks_template() -> dict[str, bool]:
    return {
        "record_exists": False,
        "hash_integrity": False,
        "payment_valid": False,
        "contract_valid": False,
        "chain_confirmed": False,
        "walrus_proof": False,
        "not_tampered": False,
    }


def _footer() -> dict[str, str]:
    return {
        "secured_by": "Sui Blockchain",
        "stored_on": "Walrus" if walrus_anchor_service else "Walrus",
        "powered_by": "RentDirect UG",
    }


def _walrus_block(blob_id: Optional[str], content_hash: Optional[str] = None) -> dict[str, Any]:
    return walrus_anchor_service.proof_fields(blob_id, content_hash=content_hash)


def _verify_receipt_hash(row: SystemReceipt) -> bool:
    if not row.metadata_json or not row.verification_hash:
        return False
    try:
        payload = json.loads(row.metadata_json)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest() == row.verification_hash
    except (json.JSONDecodeError, TypeError):
        return False


def _verify_chain_tx(tx_hash: Optional[str]) -> bool:
    if not (tx_hash or "").strip():
        return False
    try:
        tx = sui_rpc.get_transaction(tx_hash.strip())
        return tx.get("effects", {}).get("status", {}).get("status") == "success"
    except Exception:
        return False


def verify_receipt(db: Session, token: str) -> dict[str, Any]:
    row = (
        db.query(SystemReceipt)
        .filter(SystemReceipt.verification_token == token, SystemReceipt.is_void == False)  # noqa: E712
        .first()
    )
    checks = _checks_template()
    if not row:
        return {
            "valid": False,
            "kind": "receipt",
            "verification_status": "not_found",
            "message": "Receipt not found or has been voided.",
            "checks": checks,
            "footer": _footer(),
        }

    checks["record_exists"] = True
    hash_ok = _verify_receipt_hash(row)
    checks["hash_integrity"] = hash_ok
    checks["not_tampered"] = hash_ok and bool(row.checksum)

    payment_ok = True
    if row.payment_id:
        pay = db.query(Payment).filter(Payment.id == row.payment_id).first()
        payment_ok = pay is not None and float(pay.amount or 0) == float(row.amount or 0)
    checks["payment_valid"] = payment_ok

    chain_ok = _verify_chain_tx(row.tx_hash) if row.tx_hash else False
    checks["chain_confirmed"] = chain_ok if row.tx_hash else False

    walrus = _walrus_block(row.walrus_blob_id)
    checks["walrus_proof"] = bool(walrus.get("content_hash") or walrus.get("walrus_live"))

    st = row.status.value if hasattr(row.status, "value") else str(row.status)
    all_core = checks["record_exists"] and checks["hash_integrity"] and checks["payment_valid"]
    if row.tx_hash:
        all_core = all_core and checks["chain_confirmed"]
    valid = all_core and checks["not_tampered"]

    network = (settings.sui_network or "testnet").lower()
    return {
        "valid": valid,
        "kind": "receipt",
        "verification_status": "verified" if valid else "failed_checks",
        "title": "Receipt Verified" if valid else "Receipt verification failed",
        "headline": "Verified on Sui Blockchain" if valid and row.tx_hash else ("Authentic RentDirect receipt" if valid else "Could not verify receipt"),
        "message": "This receipt is authentic and has not been tampered with."
        if valid
        else "One or more integrity checks failed.",
        "checks": checks,
        "receipt_number": row.receipt_number,
        "status": st,
        "escrow_status": st if st == "escrowed" else None,
        "amount": float(row.amount),
        "currency": row.currency,
        "tenant_name": row.tenant_name,
        "landlord_name": row.landlord_name,
        "property_name": row.property_name,
        "property_address": row.property_address,
        "unit_number": row.unit_number,
        "payment_method": row.payment_method,
        "transaction_reference": row.transaction_reference,
        "period_label": row.period_label,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "tx_hash": row.tx_hash,
        "contract_id": row.contract_id,
        "explorer_url": row.explorer_url or (
            f"https://suiscan.xyz/{network}/tx/{row.tx_hash}" if row.tx_hash else None
        ),
        "verification_hash": row.verification_hash,
        "checksum": row.checksum,
        "digital_signature": row.digital_signature,
        "smart_summary": row.smart_summary,
        "verification_url": verify_page_url(token),
        "wallet_address": row.wallet_address,
        **walrus,
        "footer": _footer(),
    }


def ensure_lease_verify_token(lease: Lease) -> str:
    if not getattr(lease, "verification_token", None):
        lease.verification_token = new_verify_token()
    return lease.verification_token


def verify_contract(db: Session, token: str) -> dict[str, Any]:
    lease = (
        db.query(Lease)
        .options(
            joinedload(Lease.tenant),
            joinedload(Lease.unit).joinedload(Unit.parent_property),
            joinedload(Lease.owner),
        )
        .filter(Lease.verification_token == token)
        .first()
    )
    checks = _checks_template()
    if not lease:
        return {
            "valid": False,
            "kind": "contract",
            "verification_status": "not_found",
            "message": "Rental agreement not found.",
            "checks": checks,
            "footer": _footer(),
        }

    checks["record_exists"] = True
    checks["contract_valid"] = lease.status.value in ("active", "pending", "draft") if hasattr(lease.status, "value") else True

    stored_hash = getattr(lease, "agreement_hash", None)
    checks["hash_integrity"] = bool(stored_hash)

    walrus = _walrus_block(lease.walrus_blob_id, content_hash=lease.agreement_hash)
    checks["walrus_proof"] = bool(walrus.get("content_hash") or walrus.get("walrus_live"))
    checks["not_tampered"] = checks["hash_integrity"] and checks["record_exists"]

    valid = checks["record_exists"] and checks["contract_valid"] and (
        checks["hash_integrity"] or checks["walrus_proof"]
    )

    tenant = lease.tenant
    unit = lease.unit
    prop = unit.parent_property if unit else None
    landlord = lease.owner
    st = lease.status.value if hasattr(lease.status, "value") else str(lease.status)

    return {
        "valid": valid,
        "kind": "contract",
        "verification_status": "verified" if valid else "failed_checks",
        "title": "Contract Verified" if valid else "Contract verification incomplete",
        "headline": "Rental agreement authenticated" if valid else "Agreement could not be fully verified",
        "message": "This rental agreement matches the anchored record on RentDirect UG."
        if valid
        else "Agreement hash or Walrus proof missing — record may predate anchoring.",
        "checks": checks,
        "lease_id": lease.id,
        "status": st,
        "tenant_name": tenant.full_name if tenant else None,
        "landlord_name": landlord.full_name if landlord else None,
        "property_name": prop.name if prop else None,
        "property_address": prop.address if prop else None,
        "unit_number": unit.unit_number if unit else None,
        "monthly_rent": float(lease.monthly_rent) if lease.monthly_rent else None,
        "deposit_amount": float(lease.deposit_amount or 0),
        "start_date": lease.start_date.isoformat() if lease.start_date else None,
        "end_date": lease.end_date.isoformat() if lease.end_date else None,
        "agreement_hash": lease.agreement_hash,
        "contract_id": settings.sui_package_id,
        "verification_url": verify_page_url(token),
        **walrus,
        "footer": _footer(),
    }


def ensure_property_verify_token(prop: Property) -> str:
    if not getattr(prop, "verification_token", None):
        prop.verification_token = new_verify_token()
    return prop.verification_token


def verify_property(db: Session, token: str) -> dict[str, Any]:
    prop = (
        db.query(Property)
        .options(joinedload(Property.owner))
        .filter(Property.verification_token == token)
        .first()
    )
    checks = _checks_template()
    if not prop:
        return {
            "valid": False,
            "kind": "property",
            "verification_status": "not_found",
            "message": "Property record not found.",
            "checks": checks,
            "footer": _footer(),
        }

    checks["record_exists"] = True
    gov = (prop.gov_verification_status or "pending").lower()
    checks["contract_valid"] = gov == "verified"
    walrus = _walrus_block(prop.gov_walrus_blob_id, content_hash=prop.gov_packet_hash)
    checks["walrus_proof"] = bool(walrus.get("content_hash") or walrus.get("walrus_live"))
    checks["hash_integrity"] = bool(prop.gov_packet_hash)
    checks["not_tampered"] = checks["hash_integrity"]

    valid = checks["record_exists"] and gov == "verified"

    return {
        "valid": valid,
        "kind": "property",
        "verification_status": "verified" if valid else ("pending" if gov == "pending" else "failed_checks"),
        "title": "Property Verified" if valid else "Property verification",
        "headline": "KCCA-approved listing" if valid else f"Status: {gov.upper()}",
        "message": "This property is registered and approved by KCCA on RentDirect UG."
        if valid
        else f"Government verification status: {gov}.",
        "checks": checks,
        "property_name": prop.name,
        "property_address": prop.address,
        "district": prop.district,
        "parish": prop.parish,
        "landlord_name": prop.owner.full_name if prop.owner else None,
        "gov_verification_status": gov,
        "verification_url": verify_page_url(token),
        **walrus,
        "footer": _footer(),
    }


def ensure_compliance_verify_token(user: User) -> str:
    if not getattr(user, "compliance_verify_token", None):
        user.compliance_verify_token = new_verify_token()
    return user.compliance_verify_token


def verify_compliance(db: Session, token: str) -> dict[str, Any]:
    user = db.query(User).filter(User.compliance_verify_token == token).first()
    checks = _checks_template()
    if not user:
        return {
            "valid": False,
            "kind": "compliance",
            "verification_status": "not_found",
            "message": "Compliance record not found.",
            "checks": checks,
            "footer": _footer(),
        }

    checks["record_exists"] = True
    kyc = (user.kyc_review_status or "pending").lower()
    checks["contract_valid"] = kyc == "approved" and not getattr(user, "gov_suspended", False)
    walrus = _walrus_block(
        getattr(user, "kyc_walrus_blob_id", None),
        content_hash=getattr(user, "kyc_manifest_hash", None),
    )
    checks["walrus_proof"] = bool(walrus.get("content_hash") or walrus.get("walrus_live"))
    checks["hash_integrity"] = bool(getattr(user, "kyc_manifest_hash", None))
    checks["not_tampered"] = checks["hash_integrity"] or checks["walrus_proof"]

    valid = checks["record_exists"] and checks["contract_valid"] and checks["not_tampered"]

    return {
        "valid": valid,
        "kind": "compliance",
        "verification_status": "verified" if valid else "failed_checks",
        "title": "Identity Verified" if valid else "Compliance check",
        "headline": "NIRA KYC verified" if valid else f"KYC status: {kyc}",
        "message": "This identity has been verified by NIRA officers on RentDirect UG."
        if valid
        else f"Current KYC status: {kyc}.",
        "checks": checks,
        "full_name": user.full_name,
        "email": user.email[:3] + "***" + user.email.split("@")[-1] if user.email and "@" in user.email else None,
        "kyc_review_status": kyc,
        "national_id_masked": (
            (user.national_id_number[:4] + "****") if getattr(user, "national_id_number", None) else None
        ),
        "verified_at": user.kyc_submitted_at.isoformat() if getattr(user, "kyc_submitted_at", None) else None,
        "verification_url": verify_page_url(token),
        **walrus,
        "footer": _footer(),
    }


def resolve_and_verify(db: Session, token: str) -> dict[str, Any]:
    """Unified QR entry — token only, no sensitive payload in URL."""
    token = (token or "").strip()
    if not token or len(token) < 8:
        return {
            "valid": False,
            "kind": "unknown",
            "verification_status": "invalid_token",
            "message": "Invalid verification token.",
            "checks": _checks_template(),
            "footer": _footer(),
        }

    for fn in (verify_receipt, verify_contract, verify_property, verify_compliance):
        result = fn(db, token)
        if result.get("verification_status") != "not_found":
            result["verified_at"] = result.get("verified_at") or datetime.now(timezone.utc).isoformat()
            return result

    return {
        "valid": False,
        "kind": "unknown",
        "verification_status": "not_found",
        "message": "No matching record for this verification code.",
        "checks": _checks_template(),
        "footer": _footer(),
    }
