"""
KYC image validation — magic bytes + Pillow decode, size limits, simple heuristics
to reduce non-document / wrong-slot uploads (not a substitute for human review).
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = False

KycKind = Literal["id_front", "id_back", "selfie"]

MAX_BYTES = 8 * 1024 * 1024  # 8 MB
MIN_PIXELS_ID = 180_000  # e.g. ~600×300 — rejects tiny icons
MIN_PIXELS_SELFIE = 120_000
MAX_PIXELS = 40_000_000
MAX_EDGE = 12_000
MIN_SHORT_EDGE_ID = 280
MIN_LONG_EDGE_ID = 400
MIN_SHORT_EDGE_SELFIE = 260
MIN_LONG_EDGE_SELFIE = 320

# JPEG / PNG / WebP signatures (first bytes)
_SIG_JPEG = b"\xff\xd8\xff"
_SIG_PNG = b"\x89PNG\r\n\x1a\n"
_SIG_RIFF = b"RIFF"  # WebP starts RIFF....WEBP


def _magic_matches_image(header: bytes) -> bool:
    if len(header) < 12:
        return False
    if header.startswith(_SIG_JPEG):
        return True
    if header.startswith(_SIG_PNG):
        return True
    if header.startswith(_SIG_RIFF) and len(header) >= 12 and header[8:12] == b"WEBP":
        return True
    return False


def validate_kyc_image(data: bytes, kind: KycKind) -> tuple[int, int]:
    """
    Returns (width, height) after validation.
    Raises ValueError with user-safe message on failure.
    """
    if not data or len(data) < 32:
        raise ValueError("File is empty or too small to be a valid image.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"Image is too large (max {MAX_BYTES // (1024 * 1024)} MB).")

    head = data[:32]
    if not _magic_matches_image(head):
        raise ValueError(
            "This file is not a supported photo format. Please upload a clear JPEG, PNG, or WebP image "
            "(not a PDF, screenshot of a document app, or renamed file)."
        )

    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise ValueError(
            "The file could not be read as a real image. It may be corrupted or disguised as an image. "
            "Please take a new photo with your phone camera."
        ) from exc

    w, h = im.size
    if w < 1 or h < 1:
        raise ValueError("Invalid image dimensions.")
    if max(w, h) > MAX_EDGE:
        raise ValueError("Image dimensions are unreasonably large. Please use a normal camera photo.")

    pixels = w * h
    short_e, long_e = (min(w, h), max(w, h))

    if kind in ("id_front", "id_back"):
        if pixels < MIN_PIXELS_ID:
            raise ValueError(
                "This image is too small to be a readable ID photo. Please move closer or use a higher "
                "resolution so the entire card fills most of the frame."
            )
        if short_e < MIN_SHORT_EDGE_ID or long_e < MIN_LONG_EDGE_ID:
            raise ValueError(
                "ID images must be sharp and large enough to read text. Retake the photo with the ID "
                "filling most of the screen."
            )
        if pixels > MAX_PIXELS:
            raise ValueError("Image is too large. Please resize or use a lower megapixel setting.")
    else:  # selfie
        if pixels < MIN_PIXELS_SELFIE:
            raise ValueError("Selfie is too small. Please use your front camera and fill the frame with your face.")
        if short_e < MIN_SHORT_EDGE_SELFIE or long_e < MIN_LONG_EDGE_SELFIE:
            raise ValueError("Selfie resolution is too low. Retake in good light, shoulders and face visible.")
        if pixels > MAX_PIXELS:
            raise ValueError("Image is too large. Please use a normal selfie photo.")
        # Reduce "ID card photo uploaded as selfie": strongly landscape wide shots are usually documents.
        if w > h * 1.35:
            raise ValueError(
                "This looks like a landscape document photo, not a selfie. Please upload a portrait photo "
                "of your face (phone vertical, face centered)."
            )

    return w, h


def ext_from_magic(data: bytes) -> str:
    if data.startswith(_SIG_JPEG):
        return ".jpg"
    if data.startswith(_SIG_PNG):
        return ".png"
    return ".webp"


def kyc_user_dir(upload_root: str, user_id: int) -> Path:
    return Path(upload_root) / "kyc" / str(user_id)


def kyc_documents_complete(upload_root: str, user_id: int) -> bool:
    base = kyc_user_dir(upload_root, user_id)
    if not base.is_dir():
        return False
    for name in ("id_front", "id_back", "selfie"):
        if not any(base.glob(f"{name}.*")):
            return False
    return True
