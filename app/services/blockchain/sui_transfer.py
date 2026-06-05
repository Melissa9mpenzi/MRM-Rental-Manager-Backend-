"""Server-side Sui transfers via JSON-RPC + pysui intent signing."""
from __future__ import annotations

import base64
import logging
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.blockchain import sui_rpc
from app.services.blockchain.wallet_provision import request_testnet_gas

logger = logging.getLogger(__name__)

GAS_BUDGET = 20_000_000


def _key_material(sk: Ed25519PrivateKey) -> tuple[bytes, bytes]:
    seed = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pk = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pk


def _sign_transaction(tx_bytes_b64: str, sk: Ed25519PrivateKey) -> str:
    """Sui intent signature (flag || sig || pubkey), base64."""
    try:
        from pysui.sui.sui_crypto import SignatureScheme, SuiKeyPair
    except ImportError as exc:
        raise RuntimeError(
            "Sui signing library (pysui) is not available on the API server. "
            "Use MoMo/Pesapal or pay with an external Sui wallet."
        ) from exc

    seed, pk = _key_material(sk)
    kp = SuiKeyPair.from_pfc_bytes(SignatureScheme.ED25519, pk, seed)
    sig = kp.new_sign_secure(tx_bytes_b64)
    return sig.to_b64()


def _largest_sui_coin(address: str) -> str:
    result = sui_rpc._rpc(
        "suix_getCoins",
        [address, sui_rpc.SUI_COIN_TYPE, None, 50],
    )
    coins = result.get("data") if isinstance(result, dict) else result
    if not isinstance(coins, list) or not coins:
        raise ValueError(
            "Platform wallet has no testnet SUI yet. "
            "The server requested faucet gas — wait about a minute and try again."
        )
    best = max(coins, key=lambda c: int(c.get("balance") or 0))
    coin_id = best.get("coinObjectId")
    if not coin_id:
        raise ValueError("Could not resolve a SUI coin object for this wallet.")
    balance = int(best.get("balance") or 0)
    if balance < 2_000_000:
        raise ValueError(
            "Platform wallet SUI balance is too low for gas. "
            "Wait a minute after the faucet request and try again."
        )
    return str(coin_id)


def _build_transfer_tx_bytes(
    sender: str,
    coin_id: str,
    recipient: str,
    amount_mist: int,
) -> str:
    result = sui_rpc._rpc(
        "unsafe_transferSui",
        [sender, coin_id, str(GAS_BUDGET), recipient, str(amount_mist)],
    )
    if isinstance(result, str) and result:
        return result
    if isinstance(result, dict):
        tx = result.get("txBytes") or result.get("tx_bytes")
        if tx:
            return str(tx)
    raise ValueError("Sui node did not return transaction bytes.")


def _execute_signed_tx(tx_bytes_b64: str, signature_b64: str) -> str:
    result = sui_rpc._rpc(
        "sui_executeTransactionBlock",
        [
            tx_bytes_b64,
            [signature_b64],
            {"showEffects": True, "showBalanceChanges": True},
            "WaitForEffectsCert",
        ],
    )
    if isinstance(result, dict):
        effects = result.get("effects") or {}
        status = (effects.get("status") or {}).get("status")
        if status and status != "success":
            err = (effects.get("status") or {}).get("error") or "Sui transaction failed."
            raise ValueError(str(err))
        digest = result.get("digest")
        if digest:
            return str(digest)
    raise ValueError("Sui executeTransactionBlock did not return a digest.")


def _ensure_wallet_funded(address: str, *, attempts: int = 3) -> None:
    balance = sui_rpc.get_sui_balance(address) or 0
    if balance >= 0.01:
        return
    for _ in range(attempts):
        request_testnet_gas(address)
        time.sleep(2)
        balance = sui_rpc.get_sui_balance(address) or 0
        if balance >= 0.01:
            return


def transfer_sui(
    sk: Ed25519PrivateKey,
    *,
    sender: str,
    recipient: str,
    amount_mist: int,
) -> str:
    """Build, sign, and execute a SUI transfer. Returns transaction digest."""
    sender = (sender or "").strip()
    recipient = (recipient or "").strip()
    if not sender.startswith("0x") or not recipient.startswith("0x"):
        raise ValueError("Invalid Sui address.")
    if amount_mist < 1:
        raise ValueError("Transfer amount must be positive.")

    _ensure_wallet_funded(sender)

    coin_id = _largest_sui_coin(sender)
    tx_b64 = _build_transfer_tx_bytes(sender, coin_id, recipient, amount_mist)
    signature = _sign_transaction(tx_b64, sk)
    return _execute_signed_tx(tx_b64, signature)
