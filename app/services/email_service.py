import smtplib
import random
import string
import secrets
from urllib.parse import quote

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings


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
        msg["From"]    = settings.smtp_from
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
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
    """Send email with verify link and 6-digit OTP (same expiry as link)."""
    base = api_base_url.rstrip("/")
    q = f"email={quote(to_email)}&token={quote(token, safe='')}"
    verification_link = f"{base}/api/v1/auth/verify-email?{q}"
    subject = "Verify your RentalMGR account"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#f4f7f7;border-radius:12px;">
      <h2 style="color:#161d23;margin-bottom:8px;">Welcome to RentalMGR, {full_name}!</h2>
      <p style="color:#576e6a;margin-bottom:16px;">Use this code in the app or website to verify your email:</p>
      <div style="background:#ffffff;border-radius:10px;padding:20px;text-align:center;border:2px solid #d4e8e5;margin-bottom:20px;">
        <span style="font-size:36px;font-weight:bold;letter-spacing:8px;color:#5e8d83;">{otp}</span>
      </div>
      <p style="color:#576e6a;margin-bottom:24px;">Or click the button below:</p>
      <div style="text-align:center;margin:24px 0;">
        <a href="{verification_link}"
           style="background:#5e8d83;color:#ffffff;padding:16px 32px;border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block;">
          Verify Email Address
        </a>
      </div>
      <p style="color:#576e6a;margin-top:24px;font-size:13px;">Or copy and paste this link into your browser:</p>
      <p style="background:#ffffff;padding:12px;border-radius:6px;word-break:break-all;font-size:12px;color:#161d23;">{verification_link}</p>
      <p style="color:#576e6a;margin-top:24px;font-size:13px;">The code and link expire in <strong>15 minutes</strong>. If you didn't register, ignore this email.</p>
    </div>
    """
    return send_email(to_email, subject, html)


def send_password_reset_otp(to_email: str, otp: str) -> bool:
    subject = "Reset your RentalMGR password"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;background:#f4f7f7;border-radius:12px;">
      <h2 style="color:#161d23;margin-bottom:8px;">Password Reset Request</h2>
      <p style="color:#576e6a;margin-bottom:24px;">Use this code to reset your password:</p>
      <div style="background:#ffffff;border-radius:10px;padding:24px;text-align:center;border:2px solid #d4e8e5;">
        <span style="font-size:40px;font-weight:bold;letter-spacing:10px;color:#5e8d83;">{otp}</span>
      </div>
      <p style="color:#576e6a;margin-top:24px;font-size:13px;">This code expires in <strong>15 minutes</strong>. If you didn't request this, ignore this email.</p>
    </div>
    """
    return send_email(to_email, subject, html)