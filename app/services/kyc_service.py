"""KYC submission state — keep DB in sync with uploaded documents."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.runtime import upload_root
from app.services.blockchain import walrus_anchor_service
from app.utils.kyc_media import kyc_documents_complete


def reconcile_user_kyc_submission(db: Session, user: User) -> bool:
    """
    If a landlord/agent has all KYC images on disk but status was never set to pending
    (e.g. failed commit on serverless), fix the row so NIRA officers can review them.
    """
    if user.role not in (UserRole.landlord, UserRole.staff):
        return False
    status = (user.kyc_review_status or "none").lower()
    if status == "approved":
        return False
    if not kyc_documents_complete(upload_root(), user.id):
        return False

    changed = False
    if status != "pending":
        user.kyc_review_status = "pending"
        changed = True
    if not user.kyc_submitted_at:
        user.kyc_submitted_at = datetime.utcnow()
        changed = True
    if not getattr(user, "kyc_walrus_blob_id", None):
        walrus_anchor_service.anchor_kyc_submission(db, user)
        changed = True
    return changed


def reconcile_all_pending_kyc_uploads(db: Session) -> int:
    """Scan platform users and promote completed uploads to pending review."""
    users = (
        db.query(User)
        .filter(User.role.in_([UserRole.landlord, UserRole.staff]))
        .all()
    )
    fixed = 0
    for user in users:
        if reconcile_user_kyc_submission(db, user):
            fixed += 1
    if fixed:
        db.commit()
    return fixed
