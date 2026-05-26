import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.response import success_response
from app.services.marketplace_service import get_marketplace_listing, list_marketplace_listings

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])
logger = logging.getLogger(__name__)


@router.get("/listings")
def marketplace_listings(
    db: Session = Depends(get_db),
    search: str = Query(""),
    min_rent: float | None = Query(None, ge=0),
    max_rent: float | None = Query(None, ge=0),
    unit_type: str | None = Query(None, description="Exact backend unit_type enum value, e.g. studio, two_bedroom"),
    listing_category: str | None = Query(None, description="Marketplace label, e.g. Apartment, Villa"),
    min_bedrooms: int | None = Query(None, ge=0),
    amenities: str | None = Query(None, description="Comma-separated: WiFi,Parking,Security,..."),
):
    try:
        amenity_list = [a.strip() for a in amenities.split(",")] if amenities else None
        rows = list_marketplace_listings(
            db,
            search=search,
            min_rent=min_rent,
            max_rent=max_rent,
            unit_type=unit_type,
            listing_category=listing_category,
            min_bedrooms=min_bedrooms,
            amenities=amenity_list,
        )
        return success_response(data=rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("marketplace listings failed")
        raise HTTPException(
            status_code=500,
            detail="Marketplace listings are temporarily unavailable. Retry shortly.",
        ) from exc


@router.get("/listings/{unit_id}")
def marketplace_listing_detail(unit_id: int, db: Session = Depends(get_db)):
    row = get_marketplace_listing(db, unit_id)
    if not row:
        from app.utils.response import error_response

        raise error_response("Listing not found or no longer available.", status_code=404)
    return success_response(data=row)
