"""RentDirect platform Sui wallets — one address per user (email account), no browser extension required."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import settings

logger = logging.getLogger(__name__)

SUI_ADDRESS_FLAG = b"\x00"


def _wallet_seed(user_id: int) -> bytes:
    secret = (settings.secret_key or "change-me").encode()
    return hmac.new(secret, f"rentdirect-sui-wallet:v1:{user_id}".encode(), hashlib.sha256).digest()


def derive_keypair(user_id: int) -> tuple[Ed25519PrivateKey, str]:
    """Deterministic Ed25519 keypair → canonical Sui address (same user always gets same address)."""
    sk = Ed25519PrivateKey.from_private_bytes(_wallet_seed(user_id))
    pk_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    addr_bytes = hashlib.blake2b(SUI_ADDRESS_FLAG + pk_bytes, digest_size=32).digest()
    return sk, "0x" + addr_bytes.hex()


def request_testnet_gas(sui_address: str) -> bool:
    """Best-effort testnet faucet so demos can pay without manual funding."""
    net = (settings.sui_network or "testnet").lower()
    if net not in ("testnet", "devnet"):
        return False
    url = (
        "https://faucet.devnet.sui.io/v1/gas"
        if net == "devnet"
        else "https://faucet.testnet.sui.io/v1/gas"
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                url,
                json={"FixedAmountRequest": {"recipient": sui_address}},
            )
        if res.status_code in (200, 201, 202):
            logger.info("Faucet requested gas for %s", sui_address[:12])
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Testnet faucet failed for %s: %s", sui_address[:12], exc)
    return False


def execute_sui_transfer(
    user_id: int,
    *,
    recipient: str,
    amount_mist: int,
) -> str:
    """
    Sign and execute a simple SUI transfer from the user's platform wallet.
    Returns transaction digest. Requires ``pysui`` on the API host.
    """
    sk, sender = derive_keypair(user_id)
    recipient = (recipient or "").strip()
    if not recipient.startswith("0x"):
        raise ValueError("Invalid treasury address.")

    try:
        from pysui import SuiConfig, SyncClient
        from pysui.sui.sui_txn import SyncTransaction
    except ImportError as exc:
        raise RuntimeError(
            "Platform Sui payments require pysui on the API server. "
            "Use MoMo/card or link an external wallet."
        ) from exc

    net = (settings.sui_network or "testnet").lower()
    rpc = (settings.sui_rpc_url or "").strip()
    if rpc:
        cfg = SuiConfig.user_config(rpc_url=rpc)
    else:
        cfg = SuiConfig.default_config()

    client = SyncClient(cfg)
    pk_hex = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    client.config.set_active_address(sender)

    txn = SyncTransaction(client=client)
    txn.transfer_sui(recipient=recipient, amount=amount_mist)
    result = txn.execute(gas_budget="10000000")
    if not result.is_ok():
        raise ValueError(str(result.result_string or "Sui transfer failed"))
    digest = str(result.result_data.digest)
    return digest
