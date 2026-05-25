"""Secure government portal API — NIRA, KCCA, URA (web-only officers)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_government, require_government_agency
from app.models.user import User, UserRole
from app.services import government_service
from app.services.blockchain import walrus_anchor_service
from app.utils.response import success_response

router = APIRouter(prefix="/government", tags=["Government"])
logger = logging.getLogger(__name__)


class NiraDecisionBody(BaseModel):
    user_id: int
    decision: str  # approved | rejected | flagged
    note: Optional[str] = None


class KccaDecisionBody(BaseModel):
    property_id: int
    decision: str  # verified | rejected | inspection | illegal
    note: Optional[str] = None


class NiraSuspendBody(BaseModel):
    user_id: int
    reason: str = "Suspended by NIRA officer — fraud / identity risk."


@router.get("/overview")
def government_overview(
    db: Session = Depends(get_db),
    user: User = Depends(require_government),
):
    agency = government_service.agency_for_user(user)
    try:
        data = government_service.overview_summary(db, agency=agency)
    except Exception as exc:  # noqa: BLE001
        logger.exception("government overview failed")
        raise HTTPException(
            status_code=500,
            detail="Government overview is temporarily unavailable. Retry shortly.",
        ) from exc
    return success_response(data=data)


@router.get("/nira/queue")
def nira_queue(
    status: Optional[str] = None,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_government_agency("nira")),
):
    return success_response(
        data=government_service.nira_queue(db, status=status, limit=limit, search=search)
    )


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
    try:
        data = government_service.ura_rental_reports(db, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("URA reports failed")
        raise HTTPException(
            status_code=500,
            detail="URA reports are temporarily unavailable. Retry shortly.",
        ) from exc
    return success_response(data=data)


@router.get("/fraud/alerts")
def fraud_alerts(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(require_government),
):
    agency = government_service.agency_for_user(user)
    try:
        data = government_service.fraud_alerts(db, agency=agency, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("fraud alerts failed")
        raise HTTPException(
            status_code=500,
            detail="Fraud alerts are temporarily unavailable. Retry shortly.",
        ) from exc
    return success_response(data=data)


@router.get("/nira/blacklist")
def nira_blacklist(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_government_agency("nira")),
):
    return success_response(data=government_service.nira_blacklist(db, limit=limit))


@router.post("/nira/suspend")
def nira_suspend_user(
    body: NiraSuspendBody,
    db: Session = Depends(get_db),
    officer: User = Depends(require_government_agency("nira")),
):
    try:
        data = government_service.nira_suspend_user(
            db,
            officer_id=officer.id,
            user_id=body.user_id,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return success_response(data=data, message="Account suspended.")


@router.post("/nira/unsuspend/{user_id}")
def nira_unsuspend_user(
    user_id: int,
    db: Session = Depends(get_db),
    officer: User = Depends(require_government_agency("nira")),
):
    try:
        data = government_service.nira_unsuspend_user(db, officer_id=officer.id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return success_response(data=data, message="Suspension lifted.")


@router.get("/workflow")
def government_workflow(_: User = Depends(require_government)):
    return success_response(data=government_service.government_workflow_summary())


@router.get("/audit-logs")
def audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_government),
):
    agency = government_service.agency_for_user(user)
    return success_response(data=government_service.audit_trail(db, agency=agency, limit=limit))


@router.post("/audit/export-walrus")
def export_audit_walrus(
    limit: int = 100,
    db: Session = Depends(get_db),
    officer: User = Depends(require_government),
):
    """Bundle recent gov audit entries and publish to Walrus (hackathon Walrus track demo)."""
    agency = government_service.agency_for_user(officer)
    data = walrus_anchor_service.export_gov_audit_bundle(
        db,
        agency=agency,
        limit=limit,
        officer_id=officer.id,
    )
    return success_response(data=data, message="Audit bundle anchored on Walrus.")


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
