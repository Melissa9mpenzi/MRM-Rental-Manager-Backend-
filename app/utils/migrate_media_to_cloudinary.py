"""One-time migration of legacy /uploads media paths to Cloudinary URLs."""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import Sequence

import requests

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.conversation import Message
from app.models.maintenance import MaintenanceRequest
from app.models.payment import Payment
from app.models.property import Property
from app.models.system_receipt import SystemReceipt
from app.models.tenant import Tenant
from app.services import cloudinary_storage_service
from app.services.public_url_service import api_public_base_url

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
    return cloudinary_storage_service.upload_bytes(content, object_path, content_type=content_type)


def _build_fetch_urls(
    *,
    legacy_path: str,
    fetch_enabled: bool,
    fetch_base_url: str | None,
) -> list[str]:
    if not fetch_enabled:
        return []
    path = legacy_path.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    candidates: list[str] = []
    if fetch_base_url:
        candidates.append(f"{fetch_base_url.rstrip('/')}{path}")
    api_base = api_public_base_url().rstrip("/")
    candidates.append(f"{api_base}{path}")
    return list(dict.fromkeys(candidates))


def _upload_from_fetch_urls(fetch_urls: Sequence[str], object_path: str) -> str | None:
    for url in fetch_urls:
        try:
            res = requests.get(url, timeout=30)
            if res.status_code != 200 or not res.content:
                continue
            content_type = (res.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
            return cloudinary_storage_service.upload_bytes(res.content, object_path, content_type=content_type)
        except Exception:
            continue
    return None


def _migrate_scalar_field(
    db: Session,
    *,
    model: type,
    field_name: str,
    apply_changes: bool,
    limit: int | None,
    fetch_enabled: bool,
    fetch_base_url: str | None,
) -> tuple[int, int, int, int]:
    scanned = 0
    updated = 0
    missing_file = 0
    fetched_remote = 0
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
            fetch_urls = _build_fetch_urls(
                legacy_path=current,
                fetch_enabled=fetch_enabled,
                fetch_base_url=fetch_base_url,
            )
            if not fetch_urls:
                missing_file += 1
                continue
            if apply_changes:
                new_url = _upload_from_fetch_urls(fetch_urls, relative_path)
                if not new_url:
                    missing_file += 1
                    continue
                setattr(row, field_name, new_url)
            fetched_remote += 1
        elif apply_changes:
            new_url = _upload_local_file(local_path, relative_path)
            setattr(row, field_name, new_url)
        updated += 1
    return scanned, updated, missing_file, fetched_remote


def _migrate_payment_notes(
    db: Session,
    *,
    apply_changes: bool,
    limit: int | None,
    fetch_enabled: bool,
    fetch_base_url: str | None,
) -> tuple[int, int, int, int]:
    scanned = 0
    updated = 0
    missing_file = 0
    fetched_remote = 0
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
                fetch_urls = _build_fetch_urls(
                    legacy_path=legacy_path,
                    fetch_enabled=fetch_enabled,
                    fetch_base_url=fetch_base_url,
                )
                if not fetch_urls:
                    missing_file += 1
                    continue
                if apply_changes:
                    new_url = _upload_from_fetch_urls(fetch_urls, relative_path)
                    if not new_url:
                        missing_file += 1
                        continue
                    replaced = replaced.replace(f"[proof:{legacy_path}]", f"[proof:{new_url}]")
                fetched_remote += 1
            elif apply_changes:
                new_url = _upload_local_file(local_path, relative_path)
                replaced = replaced.replace(f"[proof:{legacy_path}]", f"[proof:{new_url}]")
            changed = True
            updated += 1
        if apply_changes and changed:
            row.notes = replaced
    return scanned, updated, missing_file, fetched_remote


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy /uploads media references to Cloudinary URLs.",
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
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="When local file is missing, try download from API URL + /uploads path.",
    )
    parser.add_argument(
        "--fetch-base-url",
        type=str,
        default=None,
        help="Optional explicit base URL for --fetch-missing (e.g. https://your-api.vercel.app).",
    )
    args = parser.parse_args()

    if not cloudinary_storage_service.is_cloudinary_configured():
        raise SystemExit(
            "Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.",
        )

    db = SessionLocal()
    try:
        total_scanned = 0
        total_updated = 0
        total_missing = 0
        total_fetched = 0
        for target in TARGET_FIELDS:
            scanned, updated, missing, fetched = _migrate_scalar_field(
                db,
                model=target.model,
                field_name=target.field,
                apply_changes=args.apply,
                limit=args.limit,
                fetch_enabled=args.fetch_missing,
                fetch_base_url=args.fetch_base_url,
            )
            total_scanned += scanned
            total_updated += updated
            total_missing += missing
            total_fetched += fetched
            print(
                f"{target.model.__name__}.{target.field}: scanned={scanned}, "
                f"migrated={updated}, missing_local_file={missing}, fetched_from_url={fetched}",
            )

        scanned, updated, missing, fetched = _migrate_payment_notes(
            db,
            apply_changes=args.apply,
            limit=args.limit,
            fetch_enabled=args.fetch_missing,
            fetch_base_url=args.fetch_base_url,
        )
        total_scanned += scanned
        total_updated += updated
        total_missing += missing
        total_fetched += fetched
        print(
            "Payment.notes [proof:*] tokens: "
            f"scanned={scanned}, migrated={updated}, missing_local_file={missing}, fetched_from_url={fetched}",
        )

        if args.apply:
            db.commit()
            print("Migration committed.")
        else:
            db.rollback()
            print("Dry-run only. No database changes were saved. Re-run with --apply.")

        print(
            f"TOTAL: scanned={total_scanned}, migrated={total_updated}, "
            f"missing_local_file={total_missing}, fetched_from_url={total_fetched}",
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
