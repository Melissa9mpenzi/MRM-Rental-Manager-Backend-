"""Verify Firebase Auth ID tokens (optional — requires firebase-admin + credentials path)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)
_app_initialized = False


def _ensure_firebase_app() -> bool:
    global _app_initialized
    if _app_initialized:
        return True
    path = (settings.firebase_credentials_path or "").strip()
    if not path:
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(path)
        try:
            firebase_admin.initialize_app(cred)
        except ValueError:
            pass  # default app already exists
        _app_initialized = True
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firebase Admin SDK could not initialize: %s", exc)
        return False


def verify_firebase_id_token(id_token: str) -> Optional[dict[str, Any]]:
    """
    Returns decoded token claims (uid, email, email_verified, …) or None if unavailable/invalid.
    """
    if not id_token or not str(id_token).strip():
        return None
    if not _ensure_firebase_app():
        return None
    try:
        import firebase_admin.auth as fb_auth

        return dict(fb_auth.verify_id_token(id_token.strip(), check_revoked=True))
    except Exception as exc:  # noqa: BLE001
        logger.info("Firebase ID token verification failed: %s", exc)
        return None
