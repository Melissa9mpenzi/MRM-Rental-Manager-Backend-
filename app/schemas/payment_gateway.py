from pydantic import BaseModel, Field
from typing import Optional, Any
from decimal import Decimal


class InitiateCheckoutBody(BaseModel):
    invoice_id: int
    payment_method: str = Field(..., description="mtn_momo | airtel | bank | other (card)")
    phone: Optional[str] = Field(None, description="256… required for MoMo")
    amount: Optional[Decimal] = Field(None, gt=0, description="Defaults to invoice balance_due")


class CheckoutNextAction(BaseModel):
    type: str
    message: Optional[str] = None
    payment_link: Optional[str] = None
    simulate_url: Optional[str] = None


class CheckoutOut(BaseModel):
    reference: str
    status: str
    provider: str
    amount: float
    currency: str
    payment_method: str
    invoice_id: int
    next_action: CheckoutNextAction
    payment_id: Optional[int] = None


class WebhookAck(BaseModel):
    ok: bool = True
    reference: Optional[str] = None
