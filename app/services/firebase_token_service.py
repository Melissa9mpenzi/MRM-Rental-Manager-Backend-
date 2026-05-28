"""Verify Firebase Auth ID tokens (optional — requires firebase-admin + credentials path)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services import firebase_admin_service

logger = logging.getLogger(__name__)


def verify_firebase_id_token(id_token: str) -> Optional[dict[str, Any]]:
    """
    Returns decoded token claims (uid, email, email_verified, …) or None if unavailable/invalid.
    """
    if not id_token or not str(id_token).strip():
        return None
    if not firebase_admin_service.ensure_firebase_app():
        return None
    try:
        import firebase_admin.auth as fb_auth

        return dict(fb_auth.verify_id_token(id_token.strip(), check_revoked=True))
    except Exception as exc:  # noqa: BLE001
        logger.info("Firebase ID token verification failed: %s", exc)
        return None
