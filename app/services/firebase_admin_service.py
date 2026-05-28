"""Shared Firebase Admin bootstrap (supports file path or base64 JSON env)."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)
_app_initialized = False


def _credentials_payload() -> Optional[dict[str, Any]]:
    raw_b64 = (settings.firebase_credentials_json_base64 or "").strip()
    if raw_b64:
        try:
            decoded = base64.b64decode(raw_b64).decode("utf-8")
            payload = json.loads(decoded)
            if isinstance(payload, dict):
                return payload
        except Exception as exc:  # noqa: BLE001
            logger.warning("Invalid FIREBASE_CREDENTIALS_JSON_BASE64: %s", exc)
            return None
    return None


def is_firebase_configured() -> bool:
    return bool((settings.firebase_credentials_path or "").strip() or _credentials_payload())


def ensure_firebase_app() -> bool:
    """Initialize firebase-admin exactly once."""
    global _app_initialized
    if _app_initialized:
        return True
    if not is_firebase_configured():
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred_obj = None
        payload = _credentials_payload()
        if payload:
            cred_obj = credentials.Certificate(payload)
        else:
            path = (settings.firebase_credentials_path or "").strip()
            if not path:
                return False
            cred_obj = credentials.Certificate(path)

        opts: dict[str, Any] = {}
        bucket = (settings.firebase_storage_bucket or "").strip()
        if bucket:
            opts["storageBucket"] = bucket
        try:
            firebase_admin.initialize_app(cred_obj, opts if opts else None)
        except ValueError:
            # default app already exists
            pass
        _app_initialized = True
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firebase Admin SDK could not initialize: %s", exc)
        return False
