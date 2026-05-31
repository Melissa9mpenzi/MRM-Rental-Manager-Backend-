"""Export authenticated user's platform data as JSON (GDPR-style self-service)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.conversation import MessageThread, ThreadParticipant
from app.models.payment import Payment
from app.models.tenant import Tenant
from app.models.user import User


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    tenant = db.query(Tenant).filter(Tenant.user_id == user.id).first()
    thread_ids = [
        r[0]
        for r in db.query(ThreadParticipant.thread_id)
        .filter(ThreadParticipant.user_id == user.id)
        .distinct()
        .all()
    ]
    threads = []
    if thread_ids:
        for t in db.query(MessageThread).filter(MessageThread.id.in_(thread_ids)).all():
            threads.append(
                {
                    "id": t.id,
                    "subject": t.subject,
                    "thread_type": t.thread_type.value if t.thread_type else None,
                    "listing_title": t.listing_title,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
            )

    payments = []
    if tenant:
        payments = (
            db.query(Payment)
            .filter(Payment.tenant_id == tenant.id, Payment.is_deleted.is_(False))
            .order_by(Payment.id.desc())
            .limit(500)
            .all()
        )

    return {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "national_id_number": user.national_id_number,
            "email_verified": user.email_verified,
            "kyc_review_status": user.kyc_review_status,
            "totp_enabled": bool(getattr(user, "totp_enabled", False)),
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "tenant_profile": (
            {
                "id": tenant.id,
                "full_name": tenant.full_name,
                "status": tenant.status.value if tenant and tenant.status else None,
            }
            if tenant
            else None
        ),
        "message_threads": threads,
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount or 0),
                "payment_type": p.payment_type,
                "payment_method": p.payment_method,
                "status": "recorded",
                "payment_date": str(p.payment_date) if p.payment_date else None,
            }
            for p in payments
        ],
    }
