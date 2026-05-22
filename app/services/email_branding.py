"""System logo for transactional email — Uganda coat of arms (same asset as web app)."""
from __future__ import annotations

from pathlib import Path

from app.config import settings

LOGO_CONTENT_ID = "brand-logo"
LOGO_FILENAME = "uganda-coat-of-arms.png"
LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "brand" / LOGO_FILENAME
FRONTEND_LOGO_PATH = "/images/government/uganda-coat-of-arms.png"


def resolved_logo_src_for_html() -> str | None:
    """
    Image src for email HTML.
    Priority: EMAIL_BRAND_LOGO_URL → embedded CID (bundled PNG) → FRONTEND_BASE_URL path.
    """
    explicit = (getattr(settings, "email_brand_logo_url", None) or "").strip()
    if explicit:
        return explicit
    if LOGO_PATH.is_file():
        return f"cid:{LOGO_CONTENT_ID}"
    base = (getattr(settings, "frontend_base_url", None) or "").strip().rstrip("/")
    if base:
        return f"{base}{FRONTEND_LOGO_PATH}"
    return None


def should_embed_logo_inline() -> bool:
    src = resolved_logo_src_for_html()
    return bool(src and src.startswith("cid:") and LOGO_PATH.is_file())


def logo_bytes() -> bytes | None:
    if not LOGO_PATH.is_file():
        return None
    return LOGO_PATH.read_bytes()
