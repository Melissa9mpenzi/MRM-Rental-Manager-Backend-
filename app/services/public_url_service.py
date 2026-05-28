"""Public URL helpers for links sent to users (email, QR, verify)."""
from __future__ import annotations

from app.config import settings

_FRONTEND_PROD_FALLBACK = "https://mrm-rental-manager-frontend-pink.vercel.app"
_API_PROD_FALLBACK = "https://mrm-rental-manager-backend.vercel.app"


def _is_localhost_url(url: str) -> bool:
    s = (url or "").strip().lower()
    return "localhost" in s or "127.0.0.1" in s or "0.0.0.0" in s


def frontend_base_url() -> str:
    raw = (settings.frontend_base_url or "").strip()
    if settings.is_production:
        if not raw or _is_localhost_url(raw):
            return _FRONTEND_PROD_FALLBACK
        return raw.rstrip("/")
    return (raw or "http://localhost:5173").rstrip("/")


def api_public_base_url() -> str:
    raw = (settings.api_public_base_url or "").strip()
    if settings.is_production:
        if not raw or _is_localhost_url(raw):
            return _API_PROD_FALLBACK
        return raw.rstrip("/")
    return (raw or "http://localhost:8000").rstrip("/")
