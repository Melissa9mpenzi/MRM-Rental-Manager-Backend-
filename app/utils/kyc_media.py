"""
KYC image validation — decode many camera formats, normalize to JPEG, and apply
heuristics so wrong slot types (selfie as ID, landscape doc as selfie, tiny icons) are rejected.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from PIL import Image, ImageFile, ImageStat

ImageFile.LOAD_TRUNCATED_IMAGES = False

try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
except ImportError:
    pass

KycKind = Literal["id_front", "id_back", "selfie"]

MAX_BYTES = 12 * 1024 * 1024  # 12 MB before processing
MIN_BYTES = 800
MIN_PIXELS_ID = 160_000
MIN_PIXELS_SELFIE = 100_000
MAX_PIXELS = 45_000_000
MAX_EDGE = 14_000
MIN_SHORT_EDGE_ID = 260
MIN_LONG_EDGE_ID = 380
MIN_SHORT_EDGE_SELFIE = 240
MIN_LONG_EDGE_SELFIE = 300
# Typical ID card ~ 1.4–1.8 (ISO); allow some margin
ID_ASPECT_MIN = 1.12  # width / height (landscape)
ID_ASPECT_MAX = 3.4
SELFIE_MIN_HEIGHT_RATIO = 0.92  # height / width (portrait)
MIN_COLOR_STD = 12.0  # reject near-solid colour “images”

_SIG_JPEG = b"\xff\xd8\xff"
_SIG_PNG = b"\x89PNG\r\n\x1a\n"
_SIG_RIFF = b"RIFF"
_SIG_GIF = b"GIF87a", b"GIF89a"
_SIG_BMP = b"BM"
_SIG_TIFF_LE = b"II*\x00"
_SIG_TIFF_BE = b"MM\x00*"


def content_type_allowed(content_type: str | None) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct or ct == "application/octet-stream":
        return True
    return ct.startswith("image/")


def _magic_looks_like_image(header: bytes) -> bool:
    if len(header) < 12:
        return False
    if header.startswith(_SIG_JPEG):
        return True
    if header.startswith(_SIG_PNG):
        return True
    if header.startswith(_SIG_RIFF) and len(header) >= 12 and header[8:12] == b"WEBP":
        return True
    if header.startswith(_SIG_GIF):
        return True
    if header.startswith(_SIG_BMP):
        return True
    if header.startswith(_SIG_TIFF_LE) or header.startswith(_SIG_TIFF_BE):
        return True
    return False


def _open_rgb_image(data: bytes) -> Image.Image:
    if not data or len(data) < MIN_BYTES:
        raise ValueError("File is empty or too small to be a valid photo.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"Image is too large (max {MAX_BYTES // (1024 * 1024)} MB).")

    if not _magic_looks_like_image(data[:32]):
        raise ValueError(
            "This is not a supported photo. Upload a picture from your camera or gallery "
            "(JPEG, PNG, WebP, HEIC, GIF, BMP, TIFF, etc.) — not PDF, Word, or renamed non-images."
        )

    try:
        im = Image.open(io.BytesIO(data))
        if getattr(im, "is_animated", False):
            im.seek(0)
        im.load()
    except Exception as exc:
        raise ValueError(
            "Could not read this as a real image. It may be corrupted or not a photo. "
            "Please take a new picture with your phone camera."
        ) from exc

    if im.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", im.size, (255, 255, 255))
        if im.mode == "P":
            im = im.convert("RGBA")
        if im.mode in ("RGBA", "LA"):
            background.paste(im, mask=im.split()[-1])
            im = background
        else:
            im = im.convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")

    return im


def _color_variation_ok(im: Image.Image) -> bool:
    """Reject blank screens, single-colour placeholders, and tiny icons."""
    thumb = im.copy()
    thumb.thumbnail((320, 320))
    stat = ImageStat.Stat(thumb)
    if max(stat.stddev) < MIN_COLOR_STD:
        raise ValueError(
            "This image looks blank or like a flat graphic, not a real ID or face photo. "
            "Please upload a clear camera picture."
        )
    return True


def _validate_id_framing(w: int, h: int) -> None:
    if h < 1 or w < 1:
        raise ValueError("Invalid image dimensions.")
    aspect = w / h
    if h >= w * 1.05:
        raise ValueError(
            "This looks like a portrait photo, not an ID card. For ID front/back, hold the phone "
            "horizontally and fill the frame with the flat card (landscape)."
        )
    if aspect < ID_ASPECT_MIN:
        raise ValueError(
            "This does not look like a standard ID card shape. Retake with the full card visible "
            "in landscape (not a tall strip or extreme crop)."
        )
    if aspect > ID_ASPECT_MAX:
        raise ValueError(
            "This image is too wide and thin to be a readable ID. Center the full card in the frame."
        )


def _validate_selfie_framing(w: int, h: int) -> None:
    if h < 1 or w < 1:
        raise ValueError("Invalid image dimensions.")
    if w > h * 1.2:
        raise ValueError(
            "This looks like a landscape document or table photo, not a selfie. "
            "Hold your phone vertically and take a portrait photo of your face."
        )
    if h < w * SELFIE_MIN_HEIGHT_RATIO:
        raise ValueError(
            "Selfie should be portrait (taller than wide), with your face centered. "
            "Do not upload a photo of your ID lying on a surface."
        )


def validate_kyc_image(data: bytes, kind: KycKind) -> tuple[int, int]:
    """Validate framing; returns (width, height) of decoded image."""
    im = _open_rgb_image(data)
    _color_variation_ok(im)
    w, h = im.size

    if max(w, h) > MAX_EDGE:
        raise ValueError("Image dimensions are too large. Use a normal camera photo.")
    pixels = w * h
    short_e, long_e = min(w, h), max(w, h)

    if kind in ("id_front", "id_back"):
        if pixels < MIN_PIXELS_ID:
            raise ValueError(
                "ID image is too small. Move closer so the card fills most of the photo and text is readable."
            )
        if short_e < MIN_SHORT_EDGE_ID or long_e < MIN_LONG_EDGE_ID:
            raise ValueError("ID photo resolution is too low. Retake in good light with the full card visible.")
        if pixels > MAX_PIXELS:
            raise ValueError("Image is too large. Use a lower resolution or crop closer to the card.")
        _validate_id_framing(w, h)
    else:
        if pixels < MIN_PIXELS_SELFIE:
            raise ValueError("Selfie is too small. Use your front camera and fill the frame with your face.")
        if short_e < MIN_SHORT_EDGE_SELFIE or long_e < MIN_LONG_EDGE_SELFIE:
            raise ValueError("Selfie resolution is too low. Retake with face and shoulders visible.")
        if pixels > MAX_PIXELS:
            raise ValueError("Image is too large. Use a normal selfie photo.")
        _validate_selfie_framing(w, h)

    return w, h


def normalize_kyc_image_jpeg(data: bytes, kind: KycKind, *, quality: int = 88) -> bytes:
    """Validate, then return JPEG bytes for storage."""
    im = _open_rgb_image(data)
    _color_variation_ok(im)
    w, h = im.size
    if kind in ("id_front", "id_back"):
        _validate_id_framing(w, h)
    else:
        _validate_selfie_framing(w, h)

    if max(w, h) > MAX_EDGE:
        raise ValueError("Image dimensions are too large.")

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    out = buf.getvalue()
    if len(out) < 500:
        raise ValueError("Processed image is invalid. Please retake the photo.")
    return out


def ext_from_magic(_data: bytes) -> str:
    """Stored files are normalized JPEG."""
    return ".jpg"


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
