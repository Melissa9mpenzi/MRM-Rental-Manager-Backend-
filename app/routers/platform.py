"""Platform polish — activity feed, global search, system health."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import (
    activity_service,
    media_storage_service,
    platform_data_service,
    platform_search_service,
    production_readiness,
)
from app.dependencies import require_roles
from app.models.user import UserRole
from app.services.gateway.config import gateway_public_status, is_gateway_configured
from app.config import settings, database_url_looks_configured
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


@router.get("/data-summary")
def platform_data_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles([UserRole.system_admin])),
):
    """Live row counts from Postgres — confirms the platform is not using demo seed data."""
    return success_response(data=platform_data_service.live_data_summary(db))


@router.get("/system-status")
def platform_system_status(_: User = Depends(get_current_user)):
    ready = production_readiness.production_readiness()
    gw = ready["payments"]
    return success_response(
        data={
            "environment": settings.environment,
            "api": "operational",
            "database": "operational" if database_url_looks_configured() else "misconfigured",
            "payments": "live" if gw.get("live_payments") else ("mock" if gw.get("mock_enabled") else "not_configured"),
            "blockchain": "live" if ready["blockchain"].get("treasury_configured") else "not_configured",
            "walrus": "live" if ready["walrus_live"] else "content_hash_only",
            "ready_for_global_demo": ready["ready_for_global_demo"],
            "issues": ready["issues"],
            "warnings": ready["warnings"],
            "gateway": gw,
        }
    )


@router.get("/readiness")
def platform_readiness_public():
    """Public health + config checklist (no secrets). Use before global demos."""
    return success_response(data=production_readiness.production_readiness())


@router.get("/media-storage-status")
def platform_media_storage_status():
    """Public storage backend status (no secrets)."""
    return success_response(data=media_storage_service.storage_status())
