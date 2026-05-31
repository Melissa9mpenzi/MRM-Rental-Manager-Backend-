"""TOTP two-factor authentication (Google Authenticator compatible)."""
from __future__ import annotations

import base64
import io

import pyotp
import qrcode

from app.models.user import User


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(user: User, secret: str) -> str:
    issuer = "RentDirect UG"
    return pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer)


def qr_png_base64(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    digits = "".join(c for c in str(code) if c.isdigit())
    if len(digits) < 6:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(digits[:6], valid_window=1)
