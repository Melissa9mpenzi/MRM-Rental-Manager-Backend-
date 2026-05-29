"""Unified media storage: Cloudinary in production; local only for offline dev."""
from __future__ import annotations

import logging
import os

from app.config import settings
from app.runtime import is_serverless
from app.services import cloudinary_storage_service
from app.services import firebase_storage_service

logger = logging.getLogger(__name__)


def _requires_cloud_storage() -> bool:
    return settings.is_production or is_serverless()


def storage_status() -> dict:
    cloudinary_on = cloudinary_storage_service.is_cloudinary_configured()
    firebase_on = firebase_storage_service.is_firebase_storage_configured()
    if cloudinary_on:
        active = "cloudinary"
    elif firebase_on and not _requires_cloud_storage():
        active = "firebase"
    elif _requires_cloud_storage():
        active = "unconfigured"
    else:
        active = "local"
    return {
        "active_provider": active,
        "requires_cloud_storage": _requires_cloud_storage(),
        "providers": {
            "cloudinary": {
                "configured": cloudinary_on,
                "cloud_name": (settings.cloudinary_cloud_name or "").strip(),
                "folder": (settings.cloudinary_folder or "mrm").strip() or "mrm",
            },
            "firebase": {
                "configured": firebase_on,
                "bucket": (settings.firebase_storage_bucket or "").strip(),
            },
            "local": {
                "configured": not _requires_cloud_storage(),
                "upload_dir": settings.upload_dir,
            },
        },
    }


def save_media(
    *,
    content: bytes,
    folder: str,
    filename: str,
    upload_dir: str,
    content_type: str | None = None,
) -> str:
    """
    Save media and return a browser-fetchable URL.

    Production / Vercel: Cloudinary only (never ./uploads).
    Local dev: Cloudinary when configured, else optional local fallback.
    """
    object_path = f"{folder.strip('/')}/{filename}"

    if cloudinary_storage_service.is_cloudinary_configured():
        try:
            return cloudinary_storage_service.upload_bytes(content, object_path, content_type=content_type)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Cloudinary upload failed for {object_path}: {exc}") from exc

    if _requires_cloud_storage():
        raise RuntimeError(
            "Cloudinary is required for media in production. "
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET on Vercel."
        )

    if firebase_storage_service.is_firebase_storage_configured():
        try:
            return firebase_storage_service.upload_bytes(content, object_path, content_type=content_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Firebase upload failed for %s: %s", object_path, exc)

    local_dir = os.path.join(upload_dir, *folder.strip("/").split("/"))
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    with open(local_path, "wb") as f:
        f.write(content)
    logger.warning("Saved media locally at %s — configure Cloudinary for persistent URLs.", local_path)
    return f"/uploads/{folder.strip('/')}/{filename}"
