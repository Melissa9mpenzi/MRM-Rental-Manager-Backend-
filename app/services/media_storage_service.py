"""Unified media storage: Cloudinary/Firebase first, local /uploads fallback."""
from __future__ import annotations

import logging
import os

from app.config import settings
from app.services import cloudinary_storage_service
from app.services import firebase_storage_service

logger = logging.getLogger(__name__)


def storage_status() -> dict:
    cloudinary_on = cloudinary_storage_service.is_cloudinary_configured()
    firebase_on = firebase_storage_service.is_firebase_storage_configured()
    active = "cloudinary" if cloudinary_on else ("firebase" if firebase_on else "local")
    return {
        "active_provider": active,
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
                "configured": True,
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
    object_path = f"{folder.strip('/')}/{filename}"

    if cloudinary_storage_service.is_cloudinary_configured():
        try:
            return cloudinary_storage_service.upload_bytes(content, object_path, content_type=content_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cloudinary upload failed for %s. Falling back to next storage: %s", object_path, exc)

    if firebase_storage_service.is_firebase_storage_configured():
        try:
            return firebase_storage_service.upload_bytes(content, object_path, content_type=content_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Firebase upload failed for %s. Falling back to local storage: %s", object_path, exc)

    local_dir = os.path.join(upload_dir, *folder.strip("/").split("/"))
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    with open(local_path, "wb") as f:
        f.write(content)
    return f"/uploads/{folder.strip('/')}/{filename}"
