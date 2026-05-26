"""Sui JSON-RPC helpers — verify transfers and read transaction status."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

import httpx

from app.config import settings

SUI_COIN_TYPE = "0x2::sui::SUI"


def rpc_url() -> str:
    if (settings.sui_rpc_url or "").strip():
        return settings.sui_rpc_url.strip().rstrip("/")
    net = (settings.sui_network or "devnet").lower()
    defaults = {
        "devnet": "https://fullnode.devnet.sui.io:443",
        "testnet": "https://fullnode.testnet.sui.io:443",
        "mainnet": "https://fullnode.mainnet.sui.io:443",
    }
    return defaults.get(net, defaults["devnet"])


def _rpc(method: str, params: list[Any]) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    with httpx.Client(timeout=45.0) as client:
        res = client.post(rpc_url(), json=payload)
        res.raise_for_status()
        body = res.json()
    if body.get("error"):
        raise ValueError(body["error"].get("message") or str(body["error"]))
    return body.get("result") or {}


def get_sui_balance(address: str) -> Optional[float]:
    """Read SUI balance for an address from chain (returns SUI, not MIST)."""
    addr = (address or "").strip()
    if not addr.startswith("0x"):
        return None
    try:
        result = _rpc("suix_getBalance", [addr, SUI_COIN_TYPE])
        mist = int(result.get("totalBalance") or 0)
        return mist / 1_000_000_000
    except Exception:
        return None


def get_transaction(digest: str) -> dict[str, Any]:
    return _rpc(
        "sui_getTransactionBlock",
        [
            digest,
            {"showInput": True, "showEffects": True, "showBalanceChanges": True, "showEvents": True},
        ],
    )


def verify_sui_transfer(
    tx_digest: str,
    *,
    recipient: str,
    min_amount_mist: int,
    sender: Optional[str] = None,
) -> dict[str, Any]:
    """Confirm a successful SUI transfer to ``recipient`` of at least ``min_amount_mist``."""
    tx = get_transaction(tx_digest)
    if tx.get("effects", {}).get("status", {}).get("status") != "success":
        raise ValueError("Transaction did not succeed on-chain.")

    recipient = recipient.lower()
    sender = sender.lower() if sender else None
    received = 0

    for change in tx.get("balanceChanges") or []:
        if change.get("coinType") != SUI_COIN_TYPE:
            continue
        owner = change.get("owner") or {}
        addr = (owner.get("AddressOwner") or "").lower()
        amount = int(change.get("amount") or 0)
        if addr == recipient and amount > 0:
            received += amount
        if sender and addr == sender and amount < 0:
            continue

    if received < min_amount_mist:
        raise ValueError(
            f"Transfer amount insufficient: received {received} MIST, need {min_amount_mist} MIST."
        )

    return {"tx": tx, "received_mist": received}


def ugx_to_mist(amount_ugx: Decimal) -> int:
    """Demo conversion — configure SUI_UGX_PER_SUI for production oracle."""
    rate = Decimal(str(settings.sui_ugx_per_sui or 6_000_000))
    if rate <= 0:
        rate = Decimal("6000000")
    sui_amount = amount_ugx / rate
    return int(sui_amount * Decimal("1000000000"))
