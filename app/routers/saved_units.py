from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.dependencies import get_current_user
from app.models.saved_unit import SavedUnit
from app.models.user import User
from app.services.marketplace_service import get_unit_card
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/saved-units", tags=["Saved listings"])


class SavedUnitBody(BaseModel):
    unit_id: int = Field(..., ge=1)


@router.get("")
def list_saved(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(SavedUnit).filter(SavedUnit.user_id == current_user.id).order_by(SavedUnit.created_at.desc()).all()
    out = []
    for s in rows:
        card = get_unit_card(db, s.unit_id)
        if card:
            out.append(card)
    return success_response(data=out)


@router.post("", status_code=201)
def add_saved(
    body: SavedUnitBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exists = (
        db.query(SavedUnit)
        .filter(SavedUnit.user_id == current_user.id, SavedUnit.unit_id == body.unit_id)
        .first()
    )
    if exists:
        return success_response(data={"saved": True, "unit_id": body.unit_id})
    card = get_unit_card(db, body.unit_id)
    if not card:
        raise error_response("Unit not found or property inactive.", status_code=404)
    db.add(SavedUnit(user_id=current_user.id, unit_id=body.unit_id))
    db.commit()
    return success_response(data={"saved": True, "unit_id": body.unit_id})


@router.delete("/{unit_id}", status_code=204)
def remove_saved(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(SavedUnit).filter(SavedUnit.user_id == current_user.id, SavedUnit.unit_id == unit_id).delete()
    db.commit()
    return Response(status_code=204)
