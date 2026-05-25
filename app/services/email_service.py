import smtplib
import random
import string
import secrets

from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings
from app.services.email_branding import (
    LOGO_CONTENT_ID,
    logo_bytes,
    should_embed_logo_inline,
)
from app.services.email_templates import (
    html_email_verification,
    html_government_2fa_otp,
    html_government_invitation,
    html_password_reset,
    html_payment_receipt,
)


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def generate_verification_token(length: int = 32) -> str:
    """Generate a secure random token for email verification links."""
    return secrets.token_urlsafe(length)


def smtp_is_configured() -> bool:
    """True when minimum SMTP settings are present (host + from address)."""
    return bool((settings.smtp_host or "").strip() and (settings.smtp_from or "").strip())


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP. Returns True if the message was handed off to the server."""
    if not smtp_is_configured():
        print("[EMAIL ERROR] SMTP_FROM or SMTP_HOST is not configured.")
        return False

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    if should_embed_logo_inline():
        raw = logo_bytes()
        if raw:
            img = MIMEImage(raw, _subtype="png")
            img.add_header("Content-ID", f"<{LOGO_CONTENT_ID}>")
            img.add_header("Content-Disposition", "inline", filename="uganda-coat-of-arms.png")
            msg.attach(img)

    body = msg.as_string()

    server = None
    try:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8)
        server.sock.settimeout(8)
        server.ehlo()
        if settings.smtp_tls:
            server.starttls()
            server.ehlo()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to_email], body)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                # Gmail and others often close the socket after sendmail; mail was still delivered.
                pass


def send_registration_verification_link(
    to_email: str,
    full_name: str,
    token: str,
    *,
    api_base_url: str,
    otp: str,
) -> bool:
    """Send branded verification email — OTP only (no magic link in email)."""
    _ = api_base_url  # API callers pass this; email is OTP-only
    _ = token  # stored on user row for optional link flows; not shown in email
    subject = f"Confirm your email · {settings.email_brand_name}"
    html = html_email_verification(full_name=full_name, otp=otp)
    return send_email(to_email, subject, html)


def send_government_invitation_email(
    to_email: str,
    *,
    full_name: str,
    agency: str,
    role_label: str,
    invite_url: str,
    work_id: str,
) -> bool:
    subject = "You have been invited to RentDirect Government Portal"
    html = html_government_invitation(
        full_name=full_name,
        agency=agency,
        role_label=role_label,
        invite_url=invite_url,
        work_id=work_id,
    )
    return send_email(to_email, subject, html)


def send_password_reset_otp(to_email: str, otp: str) -> bool:
    subject = f"Password reset · {settings.email_brand_name}"
    html = html_password_reset(otp=otp)
    return send_email(to_email, subject, html)


def send_government_2fa_otp(*, to_email: str, full_name: str, otp: str) -> bool:
    subject = f"Government portal sign-in code · {settings.email_brand_name}"
    html = html_government_2fa_otp(full_name=full_name, otp=otp)
    return send_email(to_email, subject, html)


def send_payment_receipt_email(
    *,
    to: str,
    receipt_number: str,
    amount_ugx: float,
    period: str,
    property_name: str,
    verify_url: str,
    pdf_path: str | None = None,
) -> bool:
    subject = f"Receipt {receipt_number} · {settings.email_brand_name}"
    html = html_payment_receipt(
        receipt_number=receipt_number,
        amount_ugx=amount_ugx,
        period=period,
        property_name=property_name,
        verify_url=verify_url,
    )
    return send_email(to, subject, html)
