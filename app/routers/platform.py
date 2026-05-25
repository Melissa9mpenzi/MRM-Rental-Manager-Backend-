"""Platform polish — activity feed, global search, system health."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import activity_service, platform_search_service
from app.services.gateway.config import gateway_public_status, is_gateway_configured
from app.config import settings
from app.utils.response import success_response

router = APIRouter(prefix="/platform", tags=["Platform"])


@router.get("/activity")
def platform_activity(
    limit: int = 25,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success_response(data=activity_service.get_activity_feed(db, user, limit=limit))


@router.get("/search")
def platform_search(
    q: str = "",
    limit: int = 12,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success_response(data=platform_search_service.global_search(db, user, q=q, limit=limit))


@router.get("/system-status")
def platform_system_status(_: User = Depends(get_current_user)):
    gw = gateway_public_status()
    return success_response(
        data={
            "environment": settings.environment,
            "api": "operational",
            "database": "operational",
            "payments": "healthy" if is_gateway_configured() or settings.environment == "development" else "degraded",
            "blockchain": "synced" if settings.sui_treasury_address else "testnet-ready",
            "storage": "active" if settings.walrus_publisher_url else "local",
            "gateway": gw,
        }
    )
