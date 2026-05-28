"""Firebase Storage uploads for persistent media URLs."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Iterable

from app.config import settings
from app.services import firebase_admin_service

logger = logging.getLogger(__name__)


def is_firebase_storage_configured() -> bool:
    return bool(firebase_admin_service.is_firebase_configured() and (settings.firebase_storage_bucket or "").strip())


def _bucket_candidates() -> list[str]:
    raw = (settings.firebase_storage_bucket or "").strip()
    if not raw:
        return []
    # Accept either full gs:// URL or plain bucket name.
    name = raw.removeprefix("gs://").strip("/")
    candidates: list[str] = [name]
    if name.endswith(".appspot.com"):
        candidates.append(name.removesuffix(".appspot.com") + ".firebasestorage.app")
    elif name.endswith(".firebasestorage.app"):
        candidates.append(name.removesuffix(".firebasestorage.app") + ".appspot.com")
    return list(dict.fromkeys([c for c in candidates if c]))


def _try_upload_to_buckets(
    *,
    content: bytes,
    object_path: str,
    content_type: str,
    bucket_names: Iterable[str],
) -> str:
    from firebase_admin import storage
    from google.api_core.exceptions import NotFound

    last_error: Exception | None = None
    for bucket_name in bucket_names:
        try:
            bucket = storage.bucket(bucket_name)
            blob = bucket.blob(object_path.lstrip("/"))
            blob.cache_control = "public, max-age=31536000"
            blob.upload_from_string(content, content_type=content_type)
            try:
                return blob.generate_signed_url(version="v4", expiration=timedelta(days=3650), method="GET")
            except Exception:  # noqa: BLE001
                try:
                    blob.make_public()
                    return blob.public_url
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Firebase blob URL generation failed for %s: %s", object_path, exc)
                    return f"https://storage.googleapis.com/{bucket.name}/{blob.name}"
        except NotFound as exc:
            last_error = exc
            logger.warning("Firebase bucket not found: %s", bucket_name)
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            break
    if last_error:
        raise last_error
    raise RuntimeError("No Firebase Storage bucket candidates available.")


def upload_bytes(content: bytes, object_path: str, *, content_type: str | None = None) -> str:
    """
    Upload bytes to Firebase Storage and return a browser-fetchable URL.

    Uses a long-lived signed URL first (works even with private bucket rules),
    then falls back to public URL where ACLs allow it.
    """
    if not firebase_admin_service.ensure_firebase_app():
        raise RuntimeError("Firebase Storage not configured.")
    candidates = _bucket_candidates()
    if not candidates:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET is empty.")
    return _try_upload_to_buckets(
        content=content,
        object_path=object_path,
        content_type=content_type or "application/octet-stream",
        bucket_names=candidates,
    )
