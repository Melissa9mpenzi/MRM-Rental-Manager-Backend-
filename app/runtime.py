"""Deployment runtime detection (Vercel / AWS Lambda)."""
from __future__ import annotations

import os


def is_serverless() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def upload_root() -> str:
    """Writable directory for uploads (``/tmp`` on Vercel/Lambda)."""
    if is_serverless():
        return "/tmp/uploads"
    from app.config import settings

    return settings.upload_dir
