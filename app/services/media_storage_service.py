"""Unified media storage: Firebase bucket first, local /uploads fallback."""
from __future__ import annotations

import logging
import os

from app.services import firebase_storage_service

logger = logging.getLogger(__name__)


def save_media(
    *,
    content: bytes,
    folder: str,
    filename: str,
    upload_dir: str,
    content_type: str | None = None,
) -> str:
    object_path = f"{folder.strip('/')}/{filename}"

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
