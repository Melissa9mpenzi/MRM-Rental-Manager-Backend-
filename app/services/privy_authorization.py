"""Privy authorization signatures for wallet/policy owners."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings

logger = logging.getLogger(__name__)


def is_privy_authorization_configured() -> bool:
    return bool((settings.privy_authorization_private_key or "").strip())


def is_authorization_signature_error(status: int, detail: str) -> bool:
    text = (detail or "").lower()
    return status == 401 and (
        "privy-authorization-signature" in text
        or "authorization signature" in text
        or "missing_or_empty_authorization" in text
    )


def _canonicalize_payload(payload: dict[str, Any]) -> bytes:
    try:
        import rfc8785

        return rfc8785.dumps(payload)
    except Exception:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load_authorization_private_key():
    raw = (settings.privy_authorization_private_key or "").strip().replace("wallet-auth:", "")
    if not raw:
        return None
    try:
        pem = f"-----BEGIN PRIVATE KEY-----\n{raw}\n-----END PRIVATE KEY-----".encode("ascii")
        return serialization.load_pem_private_key(pem, password=None)
    except Exception:
        try:
            return serialization.load_der_private_key(base64.b64decode(raw), password=None)
        except Exception as exc:
            logger.warning("Invalid PRIVY_AUTHORIZATION_PRIVATE_KEY: %s", exc)
            return None


def generate_authorization_signature(
    *,
    method: str,
    url: str,
    body: dict[str, Any],
    app_id: Optional[str] = None,
) -> Optional[str]:
    private_key = _load_authorization_private_key()
    if not private_key:
        return None

    payload = {
        "version": 1,
        "method": method.upper(),
        "url": url.rstrip("/"),
        "body": body,
        "headers": {"privy-app-id": (app_id or settings.privy_app_id or "").strip()},
    }
    canonical = _canonicalize_payload(payload)
    signature = private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


def authorization_headers(*, method: str, url: str, body: dict[str, Any]) -> dict[str, str]:
    sig = generate_authorization_signature(method=method, url=url, body=body)
    if not sig:
        return {}
    return {"privy-authorization-signature": sig}
