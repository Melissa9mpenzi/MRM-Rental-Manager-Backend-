import smtplib
import random
import string
import secrets

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings
from app.services.email_templates import (
    html_email_verification,
    html_government_invitation,
    html_password_reset,
)


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def generate_verification_token(length: int = 32) -> str:
    """Generate a secure random token for email verification links."""
    return secrets.token_urlsafe(length)


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP. Returns True on success, False on failure."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))

        # Do not block API responses for 30s+ when SMTP is wrong or unreachable.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8) as server:
            server.sock.settimeout(8)
            server.ehlo()
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


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
