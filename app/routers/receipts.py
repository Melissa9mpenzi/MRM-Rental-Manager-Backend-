"""Enterprise receipt API — issue, verify, PDF, email, admin."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_system_admin
from app.models.user import User
from app.schemas.receipt import ReceiptEmailBody
from app.services import receipt_service
from app.utils.response import success_response

router = APIRouter(tags=["Receipts"])


@router.get("/receipts")
def list_receipts(
    receipt_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = receipt_service.list_for_user(
        db, current_user, receipt_type=receipt_type, status=status, limit=limit, offset=offset
    )
    return success_response(data=rows)


@router.get("/receipts/admin/stats")
def admin_receipt_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_system_admin),
):
    return success_response(data=receipt_service.admin_stats(db))


@router.get("/receipts/verify/{token}")
def verify_receipt_public(token: str, db: Session = Depends(get_db)):
    """Public QR verification — no auth required."""
    data = receipt_service.verify_public(db, token)
    return success_response(data=data)


@router.get("/receipts/{receipt_id}")
def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = receipt_service.get_for_user(db, receipt_id, current_user)
    return success_response(data=data)


@router.get("/receipts/{receipt_id}/pdf")
def download_receipt_pdf(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.system_receipt import SystemReceipt
    from app.runtime import upload_root

    row = db.query(SystemReceipt).filter(SystemReceipt.id == receipt_id).first()
    if not row:
        from app.utils.response import error_response

        raise error_response("Receipt not found.", status_code=404)
    if not receipt_service._can_access(current_user, row, db):
        from app.utils.response import error_response

        raise error_response("Access denied.", status_code=403)

    root = upload_root()
    pdf_path = receipt_service.ensure_pdf(db, row, root)
    full = pdf_path.replace("/uploads/", f"{root}/")
    return FileResponse(
        full,
        media_type="application/pdf",
        filename=f"{row.receipt_number}.pdf",
    )


@router.post("/receipts/{receipt_id}/email")
def email_receipt(
    receipt_id: int,
    body: ReceiptEmailBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    receipt_service.email_receipt(db, receipt_id, current_user, body.to_email)
    return success_response(message="Receipt emailed successfully")
