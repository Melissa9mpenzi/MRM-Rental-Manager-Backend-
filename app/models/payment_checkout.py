"""Pending gateway checkouts — settled into ``payments`` via webhook or mock complete."""
from sqlalchemy import Column, Integer, String, Numeric, Text, Enum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class CheckoutStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class PaymentCheckout(Base):
    __tablename__ = "payment_checkouts"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(64), unique=True, nullable=False, index=True)

    provider = Column(String(32), nullable=False, default="mock")
    status = Column(Enum(CheckoutStatus), default=CheckoutStatus.pending, nullable=False)

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="UGX", nullable=False)
    payment_method = Column(String(32), nullable=False)

    phone = Column(String(20), nullable=True)
    payer_email = Column(String(255), nullable=True)

    provider_tx_id = Column(String(128), nullable=True, index=True)
    provider_link = Column(String(512), nullable=True)
    provider_payload = Column(Text, nullable=True)

    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    failure_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=func.now(), server_default=func.now())
    updated_at = Column(DateTime, default=func.now(), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant")
    invoice = relationship("Invoice")
    payment = relationship("Payment")
