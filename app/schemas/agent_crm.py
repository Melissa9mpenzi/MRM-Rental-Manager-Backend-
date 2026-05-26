from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    source: str = "inbound"
    stage: str = "new"
    listing_title: Optional[str] = None
    property_id: Optional[int] = None
    unit_id: Optional[int] = None
    budget_ugx: Optional[Decimal] = None
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    listing_title: Optional[str] = None
    property_id: Optional[int] = None
    unit_id: Optional[int] = None
    budget_ugx: Optional[Decimal] = None
    notes: Optional[str] = None


class ClientCreate(BaseModel):
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    client_type: str = "renter"
    lead_id: Optional[int] = None
    notes: Optional[str] = None
    follow_up_at: Optional[datetime] = None


class ClientUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    client_type: Optional[str] = None
    notes: Optional[str] = None
    follow_up_at: Optional[datetime] = None


class ScheduleCreate(BaseModel):
    title: str
    event_type: str = "viewing"
    starts_at: datetime
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    property_id: Optional[int] = None
    unit_id: Optional[int] = None
    notes: Optional[str] = None


class ScheduleUpdate(BaseModel):
    title: Optional[str] = None
    event_type: Optional[str] = None
    status: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class DealCreate(BaseModel):
    title: str
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    offer_amount_ugx: Optional[Decimal] = None
    commission_ugx: Optional[Decimal] = None
    notes: Optional[str] = None


class DealUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    offer_amount_ugx: Optional[Decimal] = None
    commission_ugx: Optional[Decimal] = None
    notes: Optional[str] = None


class CommissionCreate(BaseModel):
    amount_ugx: Decimal = Field(..., gt=0)
    description: Optional[str] = None
    deal_id: Optional[int] = None
    status: str = "accrued"


class CommissionUpdate(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None
