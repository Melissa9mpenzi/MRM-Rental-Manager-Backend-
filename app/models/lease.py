from sqlalchemy import Column, Integer, String, Numeric, Text, Enum, ForeignKey, Date, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class LeaseStatus(str, enum.Enum):
    draft = "draft"           # Created but not yet active
    active = "active"         # Currently in effect
    expired = "expired"       # Past end date
    terminated = "terminated" # Ended early
    pending = "pending"       # Waiting for tenant move-in


class Lease(Base):
    __tablename__ = "leases"

    id = Column(Integer, primary_key=True, index=True)
    
    # Relationships
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Lease terms
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # Null = open-ended/month-to-month
    monthly_rent = Column(Numeric(12, 2), nullable=False)
    deposit_amount = Column(Numeric(12, 2), default=0)
    deposit_paid = Column(Boolean, default=False)
    deposit_receipt_path = Column(String(500), nullable=True)
    
    # Status and tracking
    status = Column(Enum(LeaseStatus), default=LeaseStatus.draft, nullable=False)
    termination_date = Column(Date, nullable=True)  # When actually ended
    termination_reason = Column(Text, nullable=True)
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), server_default=func.now())
    updated_at = Column(DateTime, default=func.now(), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    unit = relationship("Unit", back_populates="leases")
    owner = relationship("User", backref="leases")
    payments = relationship("Payment", back_populates="lease", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="lease", cascade="all, delete-orphan")
