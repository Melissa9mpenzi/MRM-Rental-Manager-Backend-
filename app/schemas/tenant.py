from pydantic import BaseModel
from typing import Optional
from decimal import Decimal
from datetime import date, datetime


class TenantCreate(BaseModel):
    unit_id: Optional[int] = None
    full_name: str
    phone: str
    email: Optional[str] = None
    national_id: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    lease_start: date
    lease_end: Optional[date] = None
    monthly_rent: Decimal
    deposit_amount: Decimal
    deposit_paid: bool = False
    deposit_receipt_path: Optional[str] = None
    status: str = "active"
    notes: Optional[str] = None

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v),
            date: lambda v: v.isoformat(),
        }


class TenantSelfUpdate(BaseModel):
    """Fields a logged-in tenant may update on their own record."""

    phone: Optional[str] = None
    email: Optional[str] = None
    national_id: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class TenantUpdate(BaseModel):
    unit_id: Optional[int] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    national_id: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    lease_start: Optional[date] = None
    lease_end: Optional[date] = None
    monthly_rent: Optional[Decimal] = None
    deposit_amount: Optional[Decimal] = None
    deposit_paid: Optional[bool] = None
    deposit_receipt_path: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v),
            date: lambda v: v.isoformat(),
        }


class TenantOut(BaseModel):
    id:                      int
    owner_id:                int
    unit_id:                 Optional[int] = None
    full_name:               str
    phone:                   str
    email:                   Optional[str] = None
    national_id:             Optional[str] = None
    emergency_contact_name:  Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    lease_start:             date
    lease_end:               Optional[date] = None
    monthly_rent:            Decimal
    deposit_amount:          Decimal
    deposit_paid:            bool
    deposit_receipt_path:    Optional[str] = None
    status:                  str
    notes:                   Optional[str] = None
    created_at:              Optional[datetime] = None

    # Computed from arrears service
    total_paid:        Optional[Decimal] = None
    total_owed:        Optional[Decimal] = None
    balance:           Optional[Decimal] = None
    balance_due:       Optional[Decimal] = None
    months_behind:     Optional[int] = None
    months_in_arrears: Optional[int] = None

    # Related names
    unit_number:   Optional[str] = None
    property_name: Optional[str] = None
    property_id:   Optional[int] = None

    model_config = {"from_attributes": True}