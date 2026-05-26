"""Verify Privy access tokens and load linked-account profile data."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def is_privy_configured() -> bool:
    return bool((settings.privy_app_id or "").strip() and (settings.privy_app_secret or "").strip())


def get_privy_client():
    global _client
    if not is_privy_configured():
        return None
    if _client is None:
        from privy import PrivyAPI

        _client = PrivyAPI(
            app_id=settings.privy_app_id.strip(),
            app_secret=settings.privy_app_secret.strip(),
        )
    return _client


def verify_access_token(access_token: str) -> Optional[dict[str, Any]]:
    """Returns claims dict with user_id (Privy DID) or None if invalid / not configured."""
    client = get_privy_client()
    if not client or not (access_token or "").strip():
        return None
    try:
        claims = client.users.verify_access_token(auth_token=access_token.strip())
        return dict(claims)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Privy token verification failed: %s", exc)
        return None


def fetch_privy_user(privy_user_id: str):
    client = get_privy_client()
    if not client:
        return None
    try:
        return client.users.get(privy_user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Privy user fetch failed for %s: %s", privy_user_id[:12], exc)
        return None


def _account_payload(account: Any) -> dict[str, Any]:
    if hasattr(account, "model_dump"):
        return account.model_dump()
    if isinstance(account, dict):
        return account
    return {}


def extract_profile_from_privy_user(privy_user) -> dict[str, Optional[str]]:
    """Email, display name, and Sui address from Privy linked accounts."""
    email: Optional[str] = None
    full_name: Optional[str] = None
    sui_address: Optional[str] = None

    for raw in getattr(privy_user, "linked_accounts", None) or []:
        acct = _account_payload(raw)
        atype = acct.get("type") or ""
        if atype == "email" and acct.get("address"):
            email = str(acct["address"]).strip().lower()
        elif atype == "google_oauth":
            if acct.get("email"):
                email = str(acct["email"]).strip().lower()
            if acct.get("name") and not full_name:
                full_name = str(acct["name"]).strip()
        elif atype == "apple_oauth":
            if acct.get("email"):
                email = str(acct["email"]).strip().lower()
        if acct.get("chain_type") == "sui" and acct.get("address"):
            sui_address = str(acct["address"]).strip()

    if not full_name and email:
        full_name = email.split("@")[0].replace(".", " ").title()

    return {
        "email": email,
        "full_name": full_name,
        "sui_address": sui_address,
    }
