from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, Text, Enum, ForeignKey, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class TenantStatus(str, enum.Enum):
    active   = "active"
    inactive = "inactive"
    evicted  = "evicted"


class Tenant(Base):
    __tablename__ = "tenants"

    id                      = Column(Integer, primary_key=True, index=True)
    owner_id                = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_id                 = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    unit_id                 = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)

    full_name               = Column(String(150), nullable=False)
    phone                   = Column(String(20), nullable=False)
    email                   = Column(String(255), nullable=True)
    national_id             = Column(String(50), nullable=True)
    emergency_contact_name  = Column(String(150), nullable=True)
    emergency_contact_phone = Column(String(20), nullable=True)

    lease_start             = Column(Date, nullable=False)
    lease_end               = Column(Date, nullable=True)
    monthly_rent            = Column(Numeric(12, 2), nullable=False)
    deposit_amount          = Column(Numeric(12, 2), nullable=True)
    deposit_paid            = Column(Boolean, nullable=True)
    deposit_receipt_path    = Column(String(500), nullable=True)

    status                  = Column(Enum(TenantStatus), default=TenantStatus.active)
    notes                   = Column(Text, nullable=True)
    created_at              = Column(DateTime, default=func.now(), server_default=func.now())
    updated_at              = Column(DateTime, default=func.now(), server_default=func.now(), onupdate=func.now())

    owner    = relationship("User", foreign_keys=[owner_id], backref="managed_tenants")
    user     = relationship("User", foreign_keys=[user_id], backref="tenant_profile")
    unit     = relationship("Unit", foreign_keys=[unit_id])
    payments = relationship("Payment", back_populates="tenant", cascade="all, delete-orphan")