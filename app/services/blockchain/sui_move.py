"""Execute Move calls from platform / landlord wallets."""
from __future__ import annotations

import logging
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.blockchain import sui_rpc
from app.services.blockchain.sui_transfer import (
    GAS_BUDGET,
    _ensure_wallet_funded,
    _execute_signed_tx,
    _largest_sui_coin,
    _sign_transaction,
)

logger = logging.getLogger(__name__)


def _extract_created_object_id(result: dict, *, recipient: str) -> Optional[str]:
    recipient = recipient.lower()
    effects = result.get("effects") or {}
    for created in effects.get("created") or []:
        owner = (created.get("owner") or {})
        addr = (owner.get("AddressOwner") or "").lower()
        if addr == recipient:
            ref = created.get("reference") or {}
            oid = ref.get("objectId")
            if oid:
                return str(oid)
    for event in result.get("events") or []:
        parsed = event.get("parsedJson") or {}
        if parsed.get("identity_id"):
            return str(parsed["identity_id"])
    return None


def _build_move_call_tx_bytes(
    sender: str,
    gas_coin_id: str,
    *,
    package_id: str,
    module: str,
    function: str,
    type_args: list[str],
    args: list,
) -> str:
    result = sui_rpc._rpc(
        "unsafe_moveCall",
        [
            sender,
            package_id,
            module,
            function,
            type_args,
            args,
            str(GAS_BUDGET),
            "1000",
            [gas_coin_id],
        ],
    )
    if isinstance(result, str) and result:
        return result
    if isinstance(result, dict):
        tx = result.get("txBytes") or result.get("tx_bytes")
        if tx:
            return str(tx)
    raise ValueError("Sui node did not return moveCall transaction bytes.")


def mint_property_listing_identity(
    sk: Ed25519PrivateKey,
    *,
    sender: str,
    package_id: str,
    module: str,
    property_id: int,
    location: bytes,
    listed_at_ms: int,
    recipient: str,
) -> tuple[str, Optional[str]]:
    """Mint property_identity::mint_listing_identity. Returns (tx_digest, object_id)."""
    sender = (sender or "").strip()
    recipient = (recipient or "").strip()
    package_id = (package_id or "").strip()
    if not sender.startswith("0x") or not recipient.startswith("0x"):
        raise ValueError("Invalid Sui address for property identity mint.")
    if not package_id.startswith("0x"):
        raise ValueError("SUI_PACKAGE_ID is not configured for on-chain property identities.")

    _ensure_wallet_funded(sender)
    coin_id = _largest_sui_coin(sender)

    location_arg = list(location)
    args = [str(property_id), location_arg, str(listed_at_ms), recipient]

    tx_b64 = _build_move_call_tx_bytes(
        sender,
        coin_id,
        package_id=package_id,
        module=module,
        function="mint_listing_identity",
        type_args=[],
        args=args,
    )
    signature = _sign_transaction(tx_b64, sk)
    digest = _execute_signed_tx(tx_b64, signature)

    object_id: Optional[str] = None
    try:
        tx = sui_rpc.get_transaction(digest)
        object_id = _extract_created_object_id(tx, recipient=recipient)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not parse property identity object id from tx %s: %s", digest[:16], exc)

    return digest, object_id
