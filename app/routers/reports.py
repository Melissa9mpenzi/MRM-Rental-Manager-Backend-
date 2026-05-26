from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_landlord
from app.models.user import User
from app.services.arrears_service import get_arrears_list
from app.utils.response import success_response

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/arrears")
def arrears_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_landlord),
):
    """Active tenants with balance due — scoped to this landlord."""
    rows = get_arrears_list(db, current_user.id)
    in_arrears = [r for r in rows if float(r.get("balance_due") or 0) > 0]
    total_owed = sum(float(r.get("balance_due") or 0) for r in in_arrears)
    return success_response(
        data={
            "tenants": rows,
            "in_arrears": in_arrears,
            "count": len(in_arrears),
            "total_owed": total_owed,
        }
    )
