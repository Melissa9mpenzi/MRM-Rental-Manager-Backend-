"""Customer-safe redaction for receipts, PDFs, and public verification."""
from __future__ import annotations

from typing import Optional


def mask_person_name(name: Optional[str]) -> Optional[str]:
    if not name or not str(name).strip():
        return None
    parts = str(name).strip().split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."


def mask_address(address: Optional[str]) -> Optional[str]:
    """Show area only — avoid full plot/street on public documents."""
    if not address or not str(address).strip():
        return None
    text = str(address).strip()
    if "," in text:
        segments = [s.strip() for s in text.split(",") if s.strip()]
        if len(segments) >= 2:
            return ", ".join(segments[-2:])
    if len(text) > 48:
        return text[:45].rstrip() + "…"
    return text


def mask_reference(ref: Optional[str]) -> Optional[str]:
    if not ref or not str(ref).strip():
        return None
    text = str(ref).strip()
    if len(text) <= 8:
        return text
    return f"···{text[-8:]}"


def mask_wallet_or_hash(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    if len(text) <= 12:
        return text
    return f"{text[:6]}…{text[-4:]}"


def mask_receipt_for_public(data: dict) -> dict:
    """Return a copy safe for QR verify pages and shared links."""
    out = dict(data)
    for key in ("verification_hash", "checksum", "digital_signature", "smart_summary", "walrus_blob_id"):
        out.pop(key, None)
    if out.get("tenant_name"):
        out["tenant_name"] = mask_person_name(out["tenant_name"])
    if out.get("landlord_name"):
        out["landlord_name"] = mask_person_name(out["landlord_name"])
    if out.get("property_address"):
        out["property_address"] = mask_address(out["property_address"])
    if out.get("transaction_reference"):
        out["transaction_reference"] = mask_reference(out["transaction_reference"])
    if out.get("wallet_address"):
        out["wallet_address"] = mask_wallet_or_hash(out["wallet_address"])
    if out.get("tx_hash"):
        out["tx_hash"] = mask_wallet_or_hash(out["tx_hash"])
    return out


def receipt_pdf_fields(row_dict: dict) -> dict:
    """Fields used when generating downloadable PDF receipts."""
    d = dict(row_dict)
    d["tenant_name"] = mask_person_name(d.get("tenant_name")) or d.get("tenant_name")
    d["landlord_name"] = mask_person_name(d.get("landlord_name")) or d.get("landlord_name")
    d["property_address"] = mask_address(d.get("property_address")) or d.get("property_address")
    d["transaction_reference"] = mask_reference(d.get("transaction_reference")) or "—"
    if d.get("wallet_address"):
        d["wallet_address"] = mask_wallet_or_hash(d["wallet_address"])
    if d.get("tx_hash"):
        d["tx_hash"] = mask_wallet_or_hash(d["tx_hash"])
    if d.get("walrus_blob_id"):
        d.pop("walrus_blob_id", None)
    d.pop("checksum", None)
    d.pop("digital_signature", None)
    d.pop("smart_summary", None)
    return d
