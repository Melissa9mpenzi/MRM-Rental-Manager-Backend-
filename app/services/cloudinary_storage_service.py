"""Cloudinary uploads for persistent image/video URLs."""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def is_cloudinary_configured() -> bool:
    return bool(
        (settings.cloudinary_cloud_name or "").strip()
        and (settings.cloudinary_api_key or "").strip()
        and (settings.cloudinary_api_secret or "").strip()
    )


def _resource_type(content_type: str | None, object_path: str) -> str:
    ctype = (content_type or "").lower()
    lower_path = object_path.lower()
    if ctype.startswith("video/") or lower_path.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
        return "video"
    if ctype.startswith("image/") or lower_path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    return "raw"


def upload_bytes(content: bytes, object_path: str, *, content_type: str | None = None) -> str:
    if not is_cloudinary_configured():
        raise RuntimeError("Cloudinary is not configured.")

    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name.strip(),
        api_key=settings.cloudinary_api_key.strip(),
        api_secret=settings.cloudinary_api_secret.strip(),
        secure=True,
    )

    folder = (settings.cloudinary_folder or "mrm").strip().strip("/")
    public_id = object_path.strip().lstrip("/").replace("\\", "/")
    if "." in public_id.rsplit("/", 1)[-1]:
        public_id = public_id.rsplit(".", 1)[0]
    if folder:
        public_id = f"{folder}/{public_id}"

    uploaded = cloudinary.uploader.upload(
        content,
        resource_type=_resource_type(content_type, object_path),
        public_id=public_id,
        overwrite=True,
        invalidate=False,
        unique_filename=False,
    )
    secure_url = uploaded.get("secure_url")
    if not secure_url:
        raise RuntimeError("Cloudinary upload succeeded but no secure_url returned.")
    return str(secure_url)
