"""
Transactional email HTML — table layout, inline CSS, optional hosted logo.
"""
from __future__ import annotations

import html as html_module
from typing import Optional

from app.config import settings


# Brand palette (matches RentDirect UG frontend feel)
_COLOR_BG = "#e9f0ec"
_COLOR_CARD = "#ffffff"
_COLOR_TEXT = "#0a1210"
_COLOR_MUTED = "#4a5c54"
_COLOR_ACCENT = "#00a376"
_COLOR_ACCENT_DARK = "#041208"
_COLOR_BORDER = "#c5ddd4"


def _escape(s: str) -> str:
    return html_module.escape(s or "", quote=True)


def _logo_block() -> str:
    """Hosted logo URL from .env, or inline wordmark (no external request)."""
    url = (getattr(settings, "email_brand_logo_url", None) or "").strip()
    if url:
        return f"""
            <div align="center" style="padding:0 0 24px 0;">
              <img src="{_escape(url)}" alt="{_escape(settings.email_brand_name)}" width="160" height="auto"
                   style="display:block;margin:0 auto;max-width:180px;height:auto;border:0;outline:none;text-decoration:none;" />
            </div>
            """
    return f"""
            <div align="center" style="padding:0 0 20px 0;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center">
                <tr>
                  <td align="center" valign="middle" style="width:48px;height:48px;border-radius:12px;background:{_COLOR_ACCENT};">
                    <span style="font-family:Georgia,'Times New Roman',serif;font-size:22px;font-weight:700;color:{_COLOR_ACCENT_DARK};line-height:48px;">RD</span>
                  </td>
                </tr>
              </table>
              <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:20px;font-weight:700;color:{_COLOR_TEXT};letter-spacing:-0.02em;margin-top:12px;">
                {_escape(settings.email_brand_name)}
              </div>
              <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;color:{_COLOR_MUTED};margin-top:4px;letter-spacing:0.04em;text-transform:uppercase;">
                {_escape(settings.email_product_tagline)}
              </div>
            </div>
            """


def _footer() -> str:
    support = (getattr(settings, "email_support_email", None) or "").strip()
    support_row = ""
    if support:
        support_row = f"""
        <tr>
          <td align="center" style="padding:8px 24px 0 24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;color:{_COLOR_MUTED};">
            Questions? <a href="mailto:{_escape(support)}" style="color:{_COLOR_ACCENT};text-decoration:none;font-weight:600;">{_escape(support)}</a>
          </td>
        </tr>
        """
    return f"""
    <tr>
      <td align="center" style="padding:28px 24px 20px 24px;border-top:1px solid {_COLOR_BORDER};">
        <p style="margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;color:#7a8f86;line-height:1.6;">
          You received this because someone used this address with {_escape(settings.email_brand_name)}.<br/>
          If this wasn&apos;t you, you can safely ignore this message.
        </p>
      </td>
    </tr>
    {support_row}
    <tr>
      <td align="center" style="padding:0 24px 32px 24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:10px;color:#9db0a8;">
        &copy; {_escape(settings.email_brand_name)}. All rights reserved.
      </td>
    </tr>
    """


def wrap_email(*, preheader: str, headline: str, body_html: str) -> str:
    """Full responsive-style wrapper; preheader hidden in inbox preview extension."""
    pre = _escape(preheader[:140])
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>{_escape(headline)}</title>
  <!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
</head>
<body style="margin:0;padding:0;background:{_COLOR_BG};-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:transparent;width:0;height:0;">
    {pre}
  </div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{_COLOR_BG};">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;">
          <tr>
            <td style="background:{_COLOR_CARD};border-radius:16px;box-shadow:0 4px 24px rgba(4,18,8,0.08);border:1px solid {_COLOR_BORDER};overflow:hidden;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="height:4px;background:linear-gradient(90deg,{_COLOR_ACCENT} 0%,{_COLOR_ACCENT_DARK} 100%);background-color:{_COLOR_ACCENT};"></td>
                </tr>
                <tr>
                  <td style="padding:36px 40px 8px 40px;">
                    {_logo_block()}
                    <h1 style="margin:0 0 8px 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:22px;font-weight:700;color:{_COLOR_TEXT};letter-spacing:-0.02em;line-height:1.3;text-align:center;">
                      {_escape(headline)}
                    </h1>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0 40px 36px 40px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.65;color:{_COLOR_MUTED};">
                    {body_html}
                  </td>
                </tr>
                {_footer()}
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def html_password_reset(*, otp: str) -> str:
    otp_esc = _escape(otp)
    body = f"""
    <p style="margin:0 0 20px 0;text-align:center;">Use the verification code below to set a new password. For your security, never share this code with anyone.</p>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
      <tr>
        <td align="center" style="padding:8px 0 24px 0;">
          <div style="display:inline-block;padding:20px 36px;background:{_COLOR_BG};border-radius:12px;border:1px dashed {_COLOR_BORDER};">
            <span style="font-family:'SF Mono',Consolas,Monaco,monospace;font-size:32px;font-weight:700;letter-spacing:0.45em;color:{_COLOR_ACCENT_DARK};">{otp_esc}</span>
          </div>
        </td>
      </tr>
    </table>
    <p style="margin:0;text-align:center;font-size:13px;color:{_COLOR_MUTED};">
      This code expires in <strong style="color:{_COLOR_TEXT};">15 minutes</strong>. If you did not request a password reset, you can ignore this email—your password will stay the same.
    </p>
    """
    return wrap_email(
        preheader=f"Your password reset code: {otp}",
        headline="Password reset",
        body_html=body,
    )


def html_email_verification(*, full_name: str, otp: str) -> str:
    name = _escape(full_name.strip() or "there")
    otp_esc = _escape(otp)
    body = f"""
    <p style="margin:0 0 8px 0;text-align:center;">Hi {name},</p>
    <p style="margin:0 0 20px 0;text-align:center;">Thanks for joining {_escape(settings.email_brand_name)}. Enter this code in the app or on the website to verify your email address.</p>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
      <tr>
        <td align="center" style="padding:8px 0 24px 0;">
          <div style="display:inline-block;padding:20px 36px;background:{_COLOR_BG};border-radius:12px;border:1px dashed {_COLOR_BORDER};">
            <span style="font-family:'SF Mono',Consolas,Monaco,monospace;font-size:32px;font-weight:700;letter-spacing:0.45em;color:{_COLOR_ACCENT_DARK};">{otp_esc}</span>
          </div>
        </td>
      </tr>
    </table>
    <p style="margin:0;text-align:center;font-size:13px;color:{_COLOR_MUTED};">
      This code expires in <strong style="color:{_COLOR_TEXT};">15 minutes</strong>. If you did not create an account, you can safely ignore this message.
    </p>
    """
    return wrap_email(
        preheader=f"Verify your email — code {otp}",
        headline="Confirm your email",
        body_html=body,
    )


def html_government_invitation(
    *,
    full_name: str,
    agency: str,
    role_label: str,
    invite_url: str,
    work_id: str,
) -> str:
    name = _escape(full_name.strip() or "Officer")
    body = f"""
    <p style="margin:0 0 12px 0;text-align:center;">Dear {name},</p>
    <p style="margin:0 0 16px 0;text-align:center;">
      You have been invited to the <strong>RentDirect Uganda Government Portal</strong>
      as a <strong>{_escape(role_label)}</strong> officer for <strong>{_escape(agency)}</strong>.
    </p>
    <p style="margin:0 0 8px 0;text-align:center;font-size:13px;color:{_COLOR_MUTED};">
      Work ID on file: <strong style="color:{_COLOR_TEXT};">{_escape(work_id)}</strong>
    </p>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
      <tr>
        <td align="center" style="padding:16px 0 24px 0;">
          <a href="{_escape(invite_url)}" style="display:inline-block;padding:14px 28px;background:{_COLOR_ACCENT};color:#ffffff;font-weight:700;text-decoration:none;border-radius:10px;">
            Accept secure invitation
          </a>
        </td>
      </tr>
    </table>
    <p style="margin:0;text-align:center;font-size:12px;color:{_COLOR_MUTED};">
      This link expires in <strong>7 days</strong>. Do not share it. Government accounts cannot be created via public registration.
    </p>
    """
    return wrap_email(
        preheader="Government portal invitation — RentDirect UG",
        headline="Government portal invitation",
        body_html=body,
    )
