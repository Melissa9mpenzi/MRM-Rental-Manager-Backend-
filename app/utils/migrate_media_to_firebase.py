"""One-time migration of legacy /uploads media paths to Firebase Storage URLs."""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.conversation import Message
from app.models.maintenance import MaintenanceRequest
from app.models.payment import Payment
from app.models.property import Property
from app.models.system_receipt import SystemReceipt
from app.models.tenant import Tenant
from app.services import firebase_storage_service

_PROOF_TOKEN_RE = re.compile(r"\[proof:(/uploads/[^\]]+)\]")


@dataclass(frozen=True)
class TargetField:
    model: type
    field: str


TARGET_FIELDS: tuple[TargetField, ...] = (
    TargetField(Property, "photo_path"),
    TargetField(Property, "video_path"),
    TargetField(Tenant, "deposit_receipt_path"),
    TargetField(MaintenanceRequest, "photo_path"),
    TargetField(Message, "attachment_url"),
    TargetField(Payment, "reference"),
    TargetField(SystemReceipt, "pdf_path"),
)


def _looks_like_legacy_upload_path(value: str | None) -> bool:
    if not value:
        return False
    s = value.strip()
    return s.startswith("/uploads/") or s.startswith("uploads/")


def _relative_upload_path(value: str) -> str:
    s = value.strip()
    if s.startswith("/uploads/"):
        return s.removeprefix("/uploads/").lstrip("/")
    if s.startswith("uploads/"):
        return s.removeprefix("uploads/").lstrip("/")
    return s.lstrip("/")


def _local_file_from_relative(relative_path: str) -> str:
    return os.path.normpath(os.path.join(settings.upload_dir, *relative_path.split("/")))


def _upload_local_file(local_path: str, object_path: str) -> str:
    with open(local_path, "rb") as f:
        content = f.read()
    content_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    return firebase_storage_service.upload_bytes(content, object_path, content_type=content_type)


def _migrate_scalar_field(
    db: Session,
    *,
    model: type,
    field_name: str,
    apply_changes: bool,
    limit: int | None,
) -> tuple[int, int, int]:
    scanned = 0
    updated = 0
    missing_file = 0
    attr = getattr(model, field_name)
    rows = db.query(model).filter(attr.isnot(None)).all()
    for row in rows:
        current = getattr(row, field_name, None)
        if not _looks_like_legacy_upload_path(current):
            continue
        scanned += 1
        if limit is not None and updated >= limit:
            continue
        relative_path = _relative_upload_path(current)
        local_path = _local_file_from_relative(relative_path)
        if not os.path.exists(local_path):
            missing_file += 1
            continue
        if apply_changes:
            new_url = _upload_local_file(local_path, relative_path)
            setattr(row, field_name, new_url)
        updated += 1
    return scanned, updated, missing_file


def _migrate_payment_notes(db: Session, *, apply_changes: bool, limit: int | None) -> tuple[int, int, int]:
    scanned = 0
    updated = 0
    missing_file = 0
    rows = db.query(Payment).filter(Payment.notes.isnot(None)).all()
    for row in rows:
        notes = row.notes or ""
        matches = _PROOF_TOKEN_RE.findall(notes)
        if not matches:
            continue
        scanned += 1
        replaced = notes
        changed = False
        for legacy_path in matches:
            if limit is not None and updated >= limit:
                break
            relative_path = _relative_upload_path(legacy_path)
            local_path = _local_file_from_relative(relative_path)
            if not os.path.exists(local_path):
                missing_file += 1
                continue
            if apply_changes:
                new_url = _upload_local_file(local_path, relative_path)
                replaced = replaced.replace(f"[proof:{legacy_path}]", f"[proof:{new_url}]")
            changed = True
            updated += 1
        if apply_changes and changed:
            row.notes = replaced
    return scanned, updated, missing_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy /uploads media references to Firebase Storage URLs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist DB updates. Default is dry-run report only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of files to migrate (for smoke testing).",
    )
    args = parser.parse_args()

    if not firebase_storage_service.is_firebase_storage_configured():
        raise SystemExit(
            "Firebase Storage is not configured. Set FIREBASE_STORAGE_BUCKET plus Firebase credentials first.",
        )

    db = SessionLocal()
    try:
        total_scanned = 0
        total_updated = 0
        total_missing = 0
        for target in TARGET_FIELDS:
            scanned, updated, missing = _migrate_scalar_field(
                db,
                model=target.model,
                field_name=target.field,
                apply_changes=args.apply,
                limit=args.limit,
            )
            total_scanned += scanned
            total_updated += updated
            total_missing += missing
            print(
                f"{target.model.__name__}.{target.field}: scanned={scanned}, "
                f"migrated={updated}, missing_local_file={missing}",
            )

        scanned, updated, missing = _migrate_payment_notes(db, apply_changes=args.apply, limit=args.limit)
        total_scanned += scanned
        total_updated += updated
        total_missing += missing
        print(f"Payment.notes [proof:*] tokens: scanned={scanned}, migrated={updated}, missing_local_file={missing}")

        if args.apply:
            db.commit()
            print("Migration committed.")
        else:
            db.rollback()
            print("Dry-run only. No database changes were saved. Re-run with --apply.")

        print(
            f"TOTAL: scanned={total_scanned}, migrated={total_updated}, "
            f"missing_local_file={total_missing}",
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
