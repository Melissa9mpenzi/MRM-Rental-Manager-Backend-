from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import date
from decimal import Decimal


class InvoiceCreate(BaseModel):
    lease_id: int
    period_month: int = Field(..., ge=1, le=12)
    period_year: int = Field(..., ge=2020)
    due_date: date
    rent_amount: Decimal = Field(..., gt=0)
    penalty_amount: Optional[Decimal] = 0
    discount_amount: Optional[Decimal] = 0
    description: Optional[str] = None
    notes: Optional[str] = None


class InvoicePayment(BaseModel):
    amount: Decimal = Field(..., gt=0)
    payment_method: str = "mtn_momo"
    payment_date: date
    reference: Optional[str] = None
    notes: Optional[str] = None


class InvoiceOut(BaseModel):
    id: int
    lease_id: int
    tenant_id: int
    unit_id: Optional[int]
    owner_id: int
    invoice_number: str
    period_month: int
    period_year: int
    due_date: date
    rent_amount: Decimal
    penalty_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    status: str
    description: Optional[str]
    notes: Optional[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sent_at: Optional[str] = None
    paid_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
