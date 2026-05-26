"""
Rent period reminders for active tenants.

Each tenant's billing cycle is anchored to their lease_start day-of-month (the day
they moved in). Seven days before that due date we notify the linked tenant user
(and the landlord if the tenant has no portal account).
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.notification import Notification, NotifType
from app.models.tenant import Tenant, TenantStatus

logger = logging.getLogger(__name__)

REMINDER_DAYS_BEFORE = 7  # notify during the 7 days before each cycle due date


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, calendar.monthrange(year, month)[1])


def next_rent_due_date(lease_start: date, as_of: date) -> date:
    """Next rent due on/after as_of, same day-of-month as lease_start."""
    dom = lease_start.day
    y, m = as_of.year, as_of.month
    due = date(y, m, _clamp_day(y, m, dom))
    if due < as_of:
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        due = date(y, m, _clamp_day(y, m, dom))
    return due


def rent_period_key(due: date) -> str:
    return due.isoformat()


def reminder_link(due: date) -> str:
    return f"/tenant/pay?rent_period={rent_period_key(due)}"


def is_in_reminder_window(lease_start: date, as_of: date | None = None) -> tuple[bool, date | None]:
    """
    True when as_of is within REMINDER_DAYS_BEFORE of the upcoming due date.
    Returns (should_notify, due_date).
    """
    as_of = as_of or date.today()
    if as_of < lease_start:
        return False, None

    due = next_rent_due_date(lease_start, as_of)
    if lease_start <= as_of <= due:
        days_left = (due - as_of).days
        # Any day in the week leading up to the period end / due date (once per period via dedup)
        if 1 <= days_left <= REMINDER_DAYS_BEFORE:
            return True, due
    return False, None


def _already_sent(db: Session, user_id: int, link: str) -> bool:
    return (
        db.query(Notification.id)
        .filter(
            Notification.user_id == user_id,
            Notification.notif_type == NotifType.rent_due,
            Notification.link == link,
        )
        .first()
        is not None
    )


def _fmt_ugx(amount) -> str:
    try:
        return f"UGX {float(amount):,.0f}"
    except (TypeError, ValueError):
        return "UGX —"


def process_rent_reminders(db: Session, as_of: date | None = None) -> dict[str, int]:
    """
    Scan active tenants and create rent_due notifications.
    Returns counts: tenants_checked, tenant_notified, landlord_notified, skipped.
    """
    from app.services.notification_service import create_notification

    as_of = as_of or date.today()
    stats = {"tenants_checked": 0, "tenant_notified": 0, "landlord_notified": 0, "skipped": 0}

    tenants = (
        db.query(Tenant)
        .filter(Tenant.status == TenantStatus.active, Tenant.lease_start.isnot(None))
        .all()
    )

    for tenant in tenants:
        stats["tenants_checked"] += 1
        should, due = is_in_reminder_window(tenant.lease_start, as_of)
        if not should or due is None:
            stats["skipped"] += 1
            continue

        link = reminder_link(due)
        period_end_label = due.strftime("%d %b %Y")
        rent_label = _fmt_ugx(tenant.monthly_rent)
        title = "Rent due in one week"
        message = (
            f"Your monthly rent period ends on {period_end_label} "
            f"(based on your move-in date). Please pay {rent_label} before then to avoid arrears."
        )

        if tenant.user_id:
            if _already_sent(db, tenant.user_id, link):
                stats["skipped"] += 1
                continue
            create_notification(
                db,
                tenant.user_id,
                title,
                message,
                notif_type=NotifType.rent_due,
                link=link,
            )
            stats["tenant_notified"] += 1
            _maybe_email_tenant(tenant, title, message, due)
        else:
            landlord_link = f"/landlord/tenants/{tenant.id}"
            landlord_title = f"Remind {tenant.full_name}: rent due in one week"
            landlord_msg = (
                f"{tenant.full_name}'s rent period ends on {period_end_label}. "
                f"Expected rent: {rent_label}. They do not have a portal login yet — please remind them."
            )
            if _already_sent(db, tenant.owner_id, link):
                stats["skipped"] += 1
                continue
            create_notification(
                db,
                tenant.owner_id,
                landlord_title,
                landlord_msg,
                notif_type=NotifType.rent_due,
                link=landlord_link,
            )
            stats["landlord_notified"] += 1

    if stats["tenant_notified"] or stats["landlord_notified"]:
        logger.info("Rent reminders sent: %s", stats)
    return stats


def _maybe_email_tenant(tenant: Tenant, title: str, message: str, due: date) -> None:
    email = (tenant.email or "").strip()
    if not email:
        return
    try:
        from app.services.email_service import send_email

        from app.config import settings

        pay_url = f"{settings.frontend_base_url.rstrip('/')}/tenant/pay"
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:24px;">
          <h2 style="color:#5e8d83;">{title}</h2>
          <p style="color:#333;line-height:1.5;">{message}</p>
          <p style="color:#576e6a;font-size:14px;">Due date: <strong>{due.strftime('%d %B %Y')}</strong></p>
          <p style="margin-top:24px;">
            <a href="{pay_url}" style="color:#5e8d83;">Pay rent in RentDirect UG</a>
          </p>
        </div>
        """
        send_email(email, title, html)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rent reminder email failed for tenant %s: %s", tenant.id, exc)


def run_rent_reminder_job() -> dict[str, int]:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return process_rent_reminders(db)
    finally:
        db.close()
