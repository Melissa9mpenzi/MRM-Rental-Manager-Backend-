"""Public blockchain verification — QR codes resolve here (no auth)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import verification_service
from app.utils.response import success_response

router = APIRouter(tags=["Verification"])


@router.get("/verify/receipt/{token}")
def verify_receipt_typed(token: str, db: Session = Depends(get_db)):
    return success_response(data=verification_service.verify_receipt(db, token))


@router.get("/verify/contract/{token}")
def verify_contract_typed(token: str, db: Session = Depends(get_db)):
    return success_response(data=verification_service.verify_contract(db, token))


@router.get("/verify/property/{token}")
def verify_property_typed(token: str, db: Session = Depends(get_db)):
    return success_response(data=verification_service.verify_property(db, token))


@router.get("/verify/compliance/{token}")
def verify_compliance_typed(token: str, db: Session = Depends(get_db)):
    return success_response(data=verification_service.verify_compliance(db, token))


@router.get("/verify/{token}")
def verify_unified(token: str, db: Session = Depends(get_db)):
    """Single QR URL: https://rentdirect.ug/verify/{token} — resolves receipt, contract, property, or compliance."""
    return success_response(data=verification_service.resolve_and_verify(db, token))
