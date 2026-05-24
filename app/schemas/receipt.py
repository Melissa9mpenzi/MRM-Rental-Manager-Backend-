from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ReceiptOut(BaseModel):
    id: int
    receipt_number: str
    receipt_type: str
    status: str
    amount: float
    currency: str
    payment_method: Optional[str] = None
    transaction_reference: Optional[str] = None
    tenant_name: Optional[str] = None
    landlord_name: Optional[str] = None
    property_name: Optional[str] = None
    property_address: Optional[str] = None
    unit_number: Optional[str] = None
    period_label: Optional[str] = None
    wallet_address: Optional[str] = None
    tx_hash: Optional[str] = None
    contract_id: Optional[str] = None
    walrus_blob_id: Optional[str] = None
    explorer_url: Optional[str] = None
    tax_id: Optional[str] = None
    ura_compliance_code: Optional[str] = None
    vat_amount: Optional[float] = None
    tax_percentage: Optional[float] = None
    verification_token: Optional[str] = None
    verification_url: Optional[str] = None
    pdf_url: Optional[str] = None
    smart_summary: Optional[str] = None
    payment_id: Optional[int] = None
    invoice_id: Optional[int] = None
    issued_at: Optional[datetime] = None
    checksum: Optional[str] = None

    model_config = {"from_attributes": True}


class ReceiptVerifyOut(BaseModel):
    valid: bool
    receipt_number: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    tenant_name: Optional[str] = None
    property_name: Optional[str] = None
    payment_method: Optional[str] = None
    period_label: Optional[str] = None
    tx_hash: Optional[str] = None
    explorer_url: Optional[str] = None
    verification_hash: Optional[str] = None
    checksum: Optional[str] = None
    issued_at: Optional[str] = None
    smart_summary: Optional[str] = None
    message: Optional[str] = None


class ReceiptListFilters(BaseModel):
    receipt_type: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class ReceiptEmailBody(BaseModel):
    to_email: Optional[str] = None
