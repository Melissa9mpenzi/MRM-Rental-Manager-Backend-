"""Sui rent payments signed with Privy embedded wallets (no pysui on server)."""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from app.config import settings
from app.models.user import User
from app.services import privy_token_service
from app.services.blockchain.sui_transfer import (
    _build_transfer_tx_bytes,
    _ensure_wallet_funded,
    _execute_signed_tx,
    _largest_sui_coin,
)
from app.services.privy_authorization import authorization_headers, is_authorization_signature_error
from app.services.privy_token_service import fetch_privy_user, is_privy_configured

logger = logging.getLogger(__name__)

PRIVY_API_BASE = "https://api.privy.io/v1"


def _privy_basic_auth() -> tuple[str, str]:
    app_id = (settings.privy_app_id or "").strip()
    secret = (settings.privy_app_secret or "").strip()
    basic = base64.b64encode(f"{app_id}:{secret}".encode()).decode()
    return app_id, basic


def _privy_request(
    method: str,
    path: str,
    *,
    body: Optional[dict[str, Any]] = None,
    timeout: float = 45.0,
) -> httpx.Response:
    app_id, basic = _privy_basic_auth()
    url = f"{PRIVY_API_BASE}{path}"
    json_body = body or {}
    headers = {
        "Authorization": f"Basic {basic}",
        "privy-app-id": app_id,
        "Content-Type": "application/json",
        **authorization_headers(method=method, url=url, body=json_body),
    }
    with httpx.Client(timeout=timeout) as http:
        if method.upper() == "GET":
            return http.get(url, headers=headers)
        if method.upper() == "PATCH":
            return http.patch(url, headers=headers, json=json_body)
        if method.upper() == "POST":
            return http.post(url, headers=headers, json=json_body)
        raise ValueError(f"Unsupported Privy HTTP method: {method}")


def _account_payload(account: Any) -> dict[str, Any]:
    if hasattr(account, "model_dump"):
        return account.model_dump()
    if isinstance(account, dict):
        return account
    return {}


def _collect_sui_wallet_candidates(privy_user_id: str) -> list[dict[str, Any]]:
    privy_user = fetch_privy_user(privy_user_id)
    if not privy_user:
        return []

    candidates: list[dict[str, Any]] = []
    for raw in getattr(privy_user, "linked_accounts", None) or []:
        candidates.append(_account_payload(raw))

    client = privy_token_service.get_privy_client()
    if client:
        try:
            for wallet in client.wallets.list(chain_type="sui", limit=50):
                data = _account_payload(wallet)
                if data:
                    candidates.append(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Privy wallet list failed: %s", exc)
    return candidates


def _normalize_sui_wallet(acct: dict[str, Any]) -> Optional[dict[str, str]]:
    chain = str(acct.get("chain_type") or acct.get("chainType") or "").lower()
    atype = str(acct.get("type") or "").lower()
    if chain != "sui" and atype not in ("sui", "sui_wallet"):
        return None
    wallet_id = acct.get("id") or acct.get("wallet_id")
    address = acct.get("address")
    public_key = acct.get("public_key") or acct.get("publicKey")
    if wallet_id and address:
        return {
            "id": str(wallet_id),
            "address": str(address).strip(),
            "public_key": str(public_key or "").strip(),
        }
    return None


def find_privy_sui_wallet(privy_user_id: str) -> Optional[dict[str, str]]:
    """Return Privy wallet id, Sui address, and public key for raw_sign."""
    for acct in _collect_sui_wallet_candidates(privy_user_id):
        wallet = _normalize_sui_wallet(acct)
        if wallet:
            return wallet
    return None


def find_privy_sui_wallet_by_address(privy_user_id: str, sui_address: str) -> Optional[dict[str, str]]:
    target = (sui_address or "").strip().lower()
    if not target:
        return None
    for acct in _collect_sui_wallet_candidates(privy_user_id):
        wallet = _normalize_sui_wallet(acct)
        if wallet and wallet["address"].lower() == target:
            return wallet
    return None


def resolve_privy_sui_public_key(
    privy_did: str,
    sui_address: str,
    *,
    wallet_id: Optional[str] = None,
) -> dict[str, str]:
    """Fetch Sui public key via Privy server API (linked accounts often omit it)."""
    wallet: Optional[dict[str, str]] = None
    if wallet_id:
        wallet = {"id": str(wallet_id).strip(), "address": (sui_address or "").strip()}
    if not wallet or not wallet.get("id"):
        wallet = find_privy_sui_wallet_by_address(privy_did, sui_address) or find_privy_sui_wallet(privy_did)
    if not wallet:
        raise ValueError(
            "No Privy Sui wallet found. Sign in with Google, Apple, or email on the Sui panel, then retry."
        )
    pub_key_bytes = _decode_public_key(wallet.get("public_key", ""), wallet_id=wallet.get("id"))
    policy_status = _ensure_sui_wallet_policy(wallet["id"])
    return {
        "wallet_id": wallet["id"],
        "address": wallet["address"],
        "public_key": pub_key_bytes.hex(),
        **policy_status,
    }


def _message_with_intent(tx_bytes: bytes) -> bytes:
    """Sui TransactionData intent prefix (scope=0, version=0, app_id=0)."""
    return bytes([0, 0, 0]) + tx_bytes


def _decode_signature(raw: Any) -> bytes:
    if raw is None:
        raise ValueError("Privy did not return a signature.")
    text = str(raw).strip()
    if text.startswith("0x"):
        text = text[2:]
    try:
        sig = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError("Invalid signature bytes from Privy.") from exc
    if len(sig) == 65:
        return sig[:64]
    return sig


def _decode_public_key(raw: str, wallet_id: Optional[str] = None) -> bytes:
    text = (raw or "").strip()
    if not text and wallet_id:
        client = privy_token_service.get_privy_client()
        if client:
            try:
                detail = client.wallets.get(wallet_id)
                detail_data = _account_payload(detail)
                text = str(detail_data.get("public_key") or detail_data.get("publicKey") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Privy wallet get failed for %s: %s", wallet_id[:8], exc)
    if not text:
        raise ValueError("Privy Sui wallet is missing a public key.")
    if text.startswith("0x"):
        text = text[2:]
    if len(text) == 64:
        return bytes.fromhex(text)
    try:
        import base58

        decoded = base58.b58decode(text)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    raise ValueError("Privy Sui wallet public key must be hex or base58.")


def _serialize_sui_signature(sig_bytes: bytes, pub_key_bytes: bytes) -> str:
    """Sui serialized signature: flag || sig || pubkey (base64)."""
    if len(sig_bytes) not in (64, 65):
        raise ValueError("Unexpected Privy signature length for Ed25519.")
    if len(sig_bytes) == 65:
        sig_bytes = sig_bytes[:64]
    if len(pub_key_bytes) != 32:
        raise ValueError("Unexpected Sui public key length.")
    payload = bytes([0]) + sig_bytes + pub_key_bytes
    return base64.b64encode(payload).decode()


def _get_wallet_policy_ids(wallet_id: str) -> list[str]:
    try:
        res = _privy_request("GET", f"/wallets/{wallet_id}", timeout=20.0)
        if res.status_code >= 400:
            return []
        data = res.json()
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        ids = payload.get("policy_ids") or payload.get("policyIds") or []
        return [str(x) for x in ids if x]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Privy wallet get failed for %s: %s", wallet_id[:8], exc)
        return []


def _attach_sui_wallet_policy(wallet_id: str, policy_id: str) -> tuple[bool, str]:
    """PATCH wallet with policy_ids. Returns (ok, detail)."""
    try:
        res = _privy_request(
            "PATCH",
            f"/wallets/{wallet_id}",
            body={"policy_ids": [policy_id]},
            timeout=20.0,
        )
        if res.status_code >= 400:
            detail = res.text[:400] or res.reason_phrase or "unknown error"
            logger.warning(
                "Privy wallet policy attach failed (%s) for %s: %s",
                res.status_code,
                wallet_id[:8],
                detail,
            )
            if is_authorization_signature_error(res.status_code, detail):
                return False, (
                    "Server needs PRIVY_AUTHORIZATION_PRIVATE_KEY (policy/wallet has an owner). "
                    "Attach the policy manually in Dashboard → Wallets, or remove the policy owner."
                )
            return False, detail
        return True, "attached"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Privy wallet policy attach failed for %s: %s", wallet_id[:8], exc)
        return False, str(exc)


def _ensure_sui_wallet_policy(wallet_id: str) -> dict[str, Any]:
    """Attach PRIVY_SUI_POLICY_ID to wallet so raw_sign allows SplitCoins + TransferObjects."""
    policy_id = (settings.privy_sui_policy_id or "").strip()
    if not policy_id:
        return {"configured": False, "attached": False, "detail": "PRIVY_SUI_POLICY_ID not set on API"}
    if not wallet_id:
        return {"configured": True, "attached": False, "detail": "missing wallet id"}

    existing = _get_wallet_policy_ids(wallet_id)
    if policy_id in existing:
        return {
            "configured": True,
            "attached": True,
            "verified": True,
            "policy_id": policy_id,
            "detail": "already attached",
        }

    ok, detail = _attach_sui_wallet_policy(wallet_id, policy_id)
    verified = policy_id in _get_wallet_policy_ids(wallet_id) if ok else False
    return {
        "configured": True,
        "attached": ok and verified,
        "verified": verified,
        "policy_id": policy_id,
        "detail": detail if ok else detail,
        "wallet_policy_ids": _get_wallet_policy_ids(wallet_id) if ok else existing,
    }


def ensure_privy_sui_wallet_policy(
    privy_did: str,
    sui_address: str,
    *,
    wallet_id: Optional[str] = None,
) -> dict[str, Any]:
    wallet: Optional[dict[str, str]] = None
    if wallet_id:
        wallet = {"id": str(wallet_id).strip(), "address": (sui_address or "").strip()}
    if not wallet or not wallet.get("id"):
        wallet = find_privy_sui_wallet_by_address(privy_did, sui_address) or find_privy_sui_wallet(privy_did)
    if not wallet:
        raise ValueError(
            "No Privy Sui wallet found. Sign in with Google, Apple, or email on the Sui panel, then retry."
        )
    status = _ensure_sui_wallet_policy(wallet["id"])
    return {"wallet_id": wallet["id"], "address": wallet["address"], **status}


def _raw_sign_sui_intent(wallet_id: str, intent_message: bytes) -> bytes:
    if not is_privy_configured():
        raise RuntimeError("Privy is not configured on the API server.")

    _ensure_sui_wallet_policy(wallet_id)

    body = {
        "params": {
            "bytes": intent_message.hex(),
            "encoding": "hex",
            "hash_function": "blake2b256",
        }
    }
    res = _privy_request("POST", f"/wallets/{wallet_id}/raw_sign", body=body, timeout=45.0)
    if res.status_code >= 400:
        detail = res.text[:400] or res.reason_phrase or "unknown error"
        if is_authorization_signature_error(res.status_code, detail):
            raise ValueError(
                "Privy server signing needs PRIVY_AUTHORIZATION_PRIVATE_KEY on the API "
                "(your policy or wallet has an owner). Pay will use browser signing instead — "
                "attach your ALLOW policy to the Sui wallet in Dashboard → Wallets."
            )
        if "policy" in detail.lower():
            raise ValueError(
                f"Privy policy blocked raw_sign: {detail}. "
                "Confirm your ALLOW policy is attached to this Sui wallet in Dashboard → Wallets."
            )
        raise ValueError(f"Privy raw_sign failed ({res.status_code}): {detail}")
    data = res.json()

    signature = data.get("signature")
    if signature is None and isinstance(data.get("data"), dict):
        signature = data["data"].get("signature")
    return _decode_signature(signature)


def submit_browser_signed_privy_tx(
    privy_did: str,
    sui_address: str,
    *,
    wallet_id: Optional[str],
    transaction_block_b64: str,
    signature_hex: str,
) -> tuple[str, str]:
    """Submit a browser-signed Privy Sui tx — server loads public key via app secret."""
    wallet: Optional[dict[str, str]] = None
    if wallet_id:
        wallet = {
            "id": str(wallet_id).strip(),
            "address": (sui_address or "").strip(),
            "public_key": "",
        }
    if not wallet or not wallet.get("id"):
        wallet = find_privy_sui_wallet_by_address(privy_did, sui_address) or find_privy_sui_wallet(privy_did)
    if not wallet:
        raise ValueError(
            "No Privy Sui wallet found. Sign in with Google, Apple, or email on the Sui panel, then retry."
        )

    pub_key_bytes = _decode_public_key(wallet.get("public_key", ""), wallet_id=wallet.get("id"))
    sig_bytes = _decode_signature(signature_hex)
    signature_b64 = _serialize_sui_signature(sig_bytes, pub_key_bytes)
    tx_b64 = (transaction_block_b64 or "").strip()
    if not tx_b64:
        raise ValueError("Missing Sui transaction bytes.")
    digest = _execute_signed_tx(tx_b64, signature_b64)
    return digest, wallet.get("address") or sui_address


def transfer_via_privy_wallet(
    wallet: dict[str, str],
    *,
    recipient: str,
    amount_mist: int,
) -> tuple[str, str]:
    sender = wallet["address"]
    recipient = (recipient or "").strip()
    if not sender.startswith("0x") or not recipient.startswith("0x"):
        raise ValueError("Invalid Sui address.")
    if amount_mist < 1:
        raise ValueError("Transfer amount must be positive.")

    _ensure_wallet_funded(sender)
    coin_id = _largest_sui_coin(sender)
    tx_b64 = _build_transfer_tx_bytes(sender, coin_id, recipient, amount_mist)
    tx_bytes = base64.b64decode(tx_b64)
    intent_message = _message_with_intent(tx_bytes)

    sig_bytes = _raw_sign_sui_intent(wallet["id"], intent_message)
    pub_key_bytes = _decode_public_key(wallet.get("public_key", ""), wallet_id=wallet.get("id"))
    signature_b64 = _serialize_sui_signature(sig_bytes, pub_key_bytes)
    digest = _execute_signed_tx(tx_b64, signature_b64)
    return digest, sender


def transfer_via_privy(
    user: User,
    *,
    recipient: str,
    amount_mist: int,
) -> tuple[str, str]:
    if not is_privy_configured():
        raise RuntimeError("Privy is not configured. Set PRIVY_APP_ID and PRIVY_APP_SECRET.")
    if not user.privy_did:
        raise ValueError("Link a Privy account (Google / Apple / email) to pay with Sui.")

    wallet = find_privy_sui_wallet(user.privy_did)
    if not wallet:
        raise ValueError(
            "No Privy Sui wallet found. Sign in with Privy on Pay rent and create an embedded Sui wallet."
        )
    return transfer_via_privy_wallet(wallet, recipient=recipient, amount_mist=amount_mist)


def transfer_for_privy_did(
    privy_did: str,
    *,
    recipient: str,
    amount_mist: int,
) -> tuple[str, str]:
    wallet = find_privy_sui_wallet(privy_did)
    if not wallet:
        raise ValueError(
            "No Privy Sui wallet yet. Enable Sui under Embedded wallets → Extended chains in the Privy dashboard, "
            "then open Pay rent and try again."
        )
    return transfer_via_privy_wallet(wallet, recipient=recipient, amount_mist=amount_mist)
