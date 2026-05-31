"""
Restore property photos from a folder on your laptop into Cloudinary + DB.

1. Export paths:  python -m app.utils.recover_property_photos_from_folder --list
2. Copy your original image files into ./uploads/ matching the printed paths
   (e.g. uploads/properties/abc123.jpg)
3. Upload:       python -m app.utils.recover_property_photos_from_folder --apply
"""
from __future__ import annotations

import argparse
import os

from app.config import settings
from app.database import SessionLocal
from app.models.property import Property
from app.services import cloudinary_storage_service
from app.utils.migrate_media_to_cloudinary import (
    _local_file_from_relative,
    _relative_upload_path,
    _upload_local_file,
)


def _legacy(path: str | None) -> bool:
    if not path:
        return False
    return path.startswith("/uploads/") or path.startswith("uploads/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover property photos from local uploads folder.")
    parser.add_argument("--list", action="store_true", help="Print DB paths and whether local file exists.")
    parser.add_argument("--apply", action="store_true", help="Upload found files to Cloudinary and update DB.")
    args = parser.parse_args()

    if not args.list and not args.apply:
        parser.error("Use --list or --apply")

    if args.apply and not cloudinary_storage_service.is_cloudinary_configured():
        raise SystemExit("Set CLOUDINARY_* in .env before --apply")

    db = SessionLocal()
    try:
        rows = db.query(Property).filter(Property.photo_path.isnot(None)).all()
        legacy = [p for p in rows if _legacy(p.photo_path)]
        print(f"Properties with legacy photo_path: {len(legacy)}")
        print(f"Local upload root: {os.path.abspath(settings.upload_dir)}\n")

        restored = 0
        missing = 0
        for prop in legacy:
            rel = _relative_upload_path(prop.photo_path or "")
            local = _local_file_from_relative(rel)
            exists = os.path.isfile(local)
            if args.list:
                status = "FOUND" if exists else "MISSING"
                print(f"  [{status}] id={prop.id} {prop.name!r}")
                print(f"         path: {prop.photo_path}")
                print(f"         file: {local}\n")
                continue
            if not exists:
                missing += 1
                continue
            new_url = _upload_local_file(local, rel)
            prop.photo_path = new_url
            restored += 1
            print(f"  OK id={prop.id} {prop.name!r} -> {new_url[:80]}...")

        if args.apply:
            db.commit()
            print(f"\nRestored: {restored}, still missing on disk: {missing}")
        elif args.list:
            found = sum(
                1
                for p in legacy
                if os.path.isfile(_local_file_from_relative(_relative_upload_path(p.photo_path or "")))
            )
            print(f"On disk: {found}/{len(legacy)} — copy missing files into {settings.upload_dir}/ then run --apply")
    finally:
        db.close()


if __name__ == "__main__":
    main()
