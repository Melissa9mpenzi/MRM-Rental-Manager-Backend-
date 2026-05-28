"""Firebase Storage uploads for persistent media URLs."""
from __future__ import annotations

from datetime import timedelta
import logging

from app.config import settings
from app.services import firebase_admin_service

logger = logging.getLogger(__name__)


def is_firebase_storage_configured() -> bool:
    return bool(firebase_admin_service.is_firebase_configured() and (settings.firebase_storage_bucket or "").strip())


def upload_bytes(content: bytes, object_path: str, *, content_type: str | None = None) -> str:
    """
    Upload bytes to Firebase Storage and return a browser-fetchable URL.

    Uses a long-lived signed URL first (works even with private bucket rules),
    then falls back to public URL where ACLs allow it.
    """
    if not firebase_admin_service.ensure_firebase_app():
        raise RuntimeError("Firebase Storage not configured.")

    from firebase_admin import storage

    bucket = storage.bucket(settings.firebase_storage_bucket.strip())
    blob = bucket.blob(object_path.lstrip("/"))
    blob.cache_control = "public, max-age=31536000"
    blob.upload_from_string(content, content_type=content_type or "application/octet-stream")

    try:
        return blob.generate_signed_url(version="v4", expiration=timedelta(days=3650), method="GET")
    except Exception:  # noqa: BLE001
        try:
            blob.make_public()
            return blob.public_url
        except Exception as exc:  # noqa: BLE001
            logger.warning("Firebase blob URL generation failed for %s: %s", object_path, exc)
            return f"https://storage.googleapis.com/{bucket.name}/{blob.name}"
