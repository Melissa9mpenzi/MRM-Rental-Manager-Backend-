from pydantic import BaseModel, field_validator
from typing import Optional
from decimal import Decimal
from datetime import date, datetime


class PaymentCreate(BaseModel):
    tenant_id:      int
    amount:         Decimal
    payment_type:   Optional[str] = "rent"
    payment_method: Optional[str] = "mtn_momo"
    reference:      Optional[str] = None
    period_month:   int
    period_year:    int
    payment_date:   date
    notes:          Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

    @field_validator("period_month")
    @classmethod
    def valid_month(cls, v):
        if not 1 <= v <= 12:
            raise ValueError("Month must be 1-12")
        return v


class PaymentUpdate(BaseModel):
    amount:         Optional[Decimal] = None
    payment_type:   Optional[str] = None
    payment_method: Optional[str] = None
    reference:      Optional[str] = None
    period_month:   Optional[int] = None
    period_year:    Optional[int] = None
    payment_date:   Optional[date] = None
    notes:          Optional[str] = None


class PaymentOut(BaseModel):
    id:             int
    tenant_id:      int
    unit_id:        Optional[int] = None
    owner_id:       int
    amount:         Decimal
    payment_type:   str
    payment_method: str
    reference:      Optional[str] = None
    period_month:   int
    period_year:    int
    payment_date:   date
    notes:          Optional[str] = None
    is_deleted:     bool
    created_at:     Optional[datetime] = None
    # Enriched
    tenant_name:    Optional[str] = None
    unit_number:    Optional[str] = None
    property_name:  Optional[str] = None

    model_config = {"from_attributes": True}