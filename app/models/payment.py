from sqlalchemy import Column, Integer, String, Numeric, Text, Enum, ForeignKey, Date, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class PaymentMethod(str, enum.Enum):
    mtn_momo  = "mtn_momo"
    airtel    = "airtel"
    cash      = "cash"
    bank      = "bank"
    sui       = "sui"
    other     = "other"


class PaymentType(str, enum.Enum):
    rent      = "rent"
    deposit   = "deposit"
    penalty   = "penalty"
    other     = "other"


class Payment(Base):
    __tablename__ = "payments"

    id              = Column(Integer, primary_key=True, index=True)
    tenant_id       = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id        = Column(Integer, ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id         = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount          = Column(Numeric(12, 2), nullable=False)
    payment_type    = Column(Enum(PaymentType), default=PaymentType.rent)
    payment_method  = Column(Enum(PaymentMethod), default=PaymentMethod.cash)
    reference       = Column(String(100), nullable=True)   # MoMo transaction ID
    period_month    = Column(Integer, nullable=False)       # 1-12
    period_year     = Column(Integer, nullable=False)
    payment_date    = Column(Date, nullable=False)
    notes           = Column(Text, nullable=True)
    is_deleted      = Column(Boolean, default=False)        # soft delete
    created_at      = Column(DateTime, default=func.now(), server_default=func.now())
    updated_at      = Column(DateTime, default=func.now(), server_default=func.now(), onupdate=func.now())

    # Relationships
    tenant = relationship("Tenant", back_populates="payments")
    lease  = relationship("Lease", back_populates="payments")