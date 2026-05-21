"""Secure government portal API — NIRA, KCCA, URA (web-only officers)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_government, require_government_agency
from app.models.user import User, UserRole
from app.services import government_service
from app.utils.response import success_response

router = APIRouter(prefix="/government", tags=["Government"])


class NiraDecisionBody(BaseModel):
    user_id: int
    decision: str  # approved | rejected | flagged
    note: Optional[str] = None


class KccaDecisionBody(BaseModel):
    property_id: int
    decision: str  # verified | rejected | inspection | illegal
    note: Optional[str] = None


@router.get("/overview")
def government_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_government),
):
    return success_response(data=government_service.overview_summary(db))


@router.get("/nira/queue")
def nira_queue(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_government_agency("nira")),
):
    return success_response(data=government_service.nira_queue(db, status=status, limit=limit))


@router.post("/nira/decision")
def nira_decision(
    body: NiraDecisionBody,
    db: Session = Depends(get_db),
    officer: User = Depends(require_government_agency("nira")),
):
    try:
        data = government_service.nira_decide(
            db,
            officer_id=officer.id,
            user_id=body.user_id,
            decision=body.decision,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return success_response(data=data, message="NIRA decision recorded")


@router.get("/kcca/properties")
def kcca_properties(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_government_agency("kcca")),
):
    return success_response(data=government_service.kcca_properties(db, status=status, limit=limit))


@router.post("/kcca/decision")
def kcca_decision(
    body: KccaDecisionBody,
    db: Session = Depends(get_db),
    officer: User = Depends(require_government_agency("kcca")),
):
    try:
        data = government_service.kcca_decide(
            db,
            officer_id=officer.id,
            property_id=body.property_id,
            decision=body.decision,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return success_response(data=data, message="KCCA property decision recorded")


@router.get("/ura/reports")
def ura_reports(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_government_agency("ura")),
):
    return success_response(data=government_service.ura_rental_reports(db, limit=limit))


@router.get("/fraud/alerts")
def fraud_alerts(
    limit: int = 30,
    db: Session = Depends(get_db),
    _: User = Depends(require_government),
):
    return success_response(data=government_service.fraud_alerts(db, limit=limit))


@router.get("/audit-logs")
def audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_government),
):
    return success_response(data=government_service.audit_trail(db, limit=limit))


@router.get("/me")
def government_me(current_user: User = Depends(require_government)):
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    agency = "all"
    if role == UserRole.gov_nira.value:
        agency = "nira"
    elif role == UserRole.gov_kcca.value:
        agency = "kcca"
    elif role == UserRole.gov_ura.value:
        agency = "ura"
    return success_response(
        data={
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": role,
            "agency": agency,
        }
    )
