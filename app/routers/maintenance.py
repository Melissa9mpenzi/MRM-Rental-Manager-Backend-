"""
Maintenance Router — full CRUD for maintenance requests.
All routes scoped to the authenticated landlord/owner.
"""
from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_landlord, _role_str
from app.models.user import User
from app.services import maintenance_service
from app.runtime import upload_root
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@router.get("", summary="List all maintenance requests")
def list_requests(
    status:      Optional[str] = Query(None, description="Filter: open | in_progress | resolved | closed"),
    unit_id:     Optional[int] = Query(None),
    property_id: Optional[int] = Query(None),
    db:          Session       = Depends(get_db),
    current_user: User         = Depends(get_current_user),
):
    """List maintenance requests. Admin/Staff see all for their properties. Tenants see only requests they reported."""
    if _role_str(current_user) == "tenant":
        from app.models.maintenance import MaintenanceRequest
        q = db.query(MaintenanceRequest).filter(MaintenanceRequest.reported_by == current_user.id)
        if status:
            q = q.filter(MaintenanceRequest.status == status)
        if unit_id:
            q = q.filter(MaintenanceRequest.unit_id == unit_id)
        rows = q.order_by(MaintenanceRequest.created_at.desc()).all()
        return success_response(data=[maintenance_service._enrich(r) for r in rows])

    require_landlord(current_user)
    requests = maintenance_service.list_requests(
        db,
        current_user.id,
        status=status,
        unit_id=unit_id,
        property_id=property_id,
    )
    return success_response(data=requests)


@router.get("/{request_id}", summary="Get a single maintenance request")
def get_request(
    request_id:   int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Get maintenance request with standardized response"""
    from app.models.maintenance import MaintenanceRequest
    req = db.query(MaintenanceRequest).filter(MaintenanceRequest.id == request_id).first()
    if not req:
        raise error_response("Request not found.", status_code=404)
    
    # Tenant can only view their own requests
    if _role_str(current_user) == "tenant":
        if req.reported_by != current_user.id:
            raise error_response("Access denied.", status_code=403)
        return success_response(data=maintenance_service._enrich(req))

    require_landlord(current_user)
    result = maintenance_service.get_request(db, request_id, current_user.id)
    return success_response(data=result)


@router.post("", status_code=201, summary="Create a maintenance request")
async def create_request(
    unit_id:     int            = Form(...),
    title:       str            = Form(...),
    description: Optional[str]  = Form(None),
    priority:    str            = Form("medium"),
    photo:       Optional[UploadFile] = File(None),
    db:          Session        = Depends(get_db),
    current_user: User          = Depends(get_current_user),
):
    """Create a maintenance request. Tenants can only submit for their own unit. Staff/Admin can submit for any unit."""
    from app.models.tenant import Tenant
    from app.models.lease import Lease, LeaseStatus
    
    # Determine owner_id and verify permissions
    if _role_str(current_user) == "tenant":
        # Tenant must be linked to this unit via active lease
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        if not tenant:
            raise error_response("Tenant profile not found.", status_code=403)
        
        lease = db.query(Lease).filter(
            Lease.tenant_id == tenant.id,
            Lease.unit_id == unit_id,
            Lease.status == LeaseStatus.active
        ).first()
        if not lease:
            raise error_response("You can only submit requests for your assigned unit.", status_code=403)
        
        owner_id = lease.owner_id
        reported_by = current_user.id
    else:
        require_landlord(current_user)
        owner_id = current_user.id
        reported_by = current_user.id
    
    result = maintenance_service.create_request(
        db=db,
        owner_id=owner_id,
        unit_id=unit_id,
        title=title,
        description=description,
        priority=priority,
        upload_dir=upload_root(),
        photo=photo,
        reported_by=reported_by,
    )
    return success_response(data=result, message="Maintenance request created successfully")


@router.patch("/{request_id}", summary="Update status/notes/cost of a request")
def update_request(
    request_id:      int,
    status:          Optional[str] = Form(None),
    resolution_note: Optional[str] = Form(None),
    cost_incurred:   Optional[str] = Form(None),
    priority:        Optional[str] = Form(None),
    title:           Optional[str] = Form(None),
    description:     Optional[str] = Form(None),
    db:              Session       = Depends(get_db),
    current_user:    User          = Depends(get_current_user),
):
    """Update maintenance request with standardized response"""
    require_landlord(current_user)
    result = maintenance_service.update_request(
        db=db,
        request_id=request_id,
        owner_id=current_user.id,
        status=status,
        resolution_note=resolution_note,
        cost_incurred=cost_incurred,
        priority=priority,
        title=title,
        description=description,
    )
    return success_response(data=result, message="Maintenance request updated successfully")


@router.delete("/{request_id}", summary="Delete a maintenance request")
def delete_request(
    request_id:   int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Delete maintenance request with standardized response"""
    require_landlord(current_user)
    maintenance_service.delete_request(db, request_id, current_user.id)
    return success_response(message="Maintenance request deleted successfully")
