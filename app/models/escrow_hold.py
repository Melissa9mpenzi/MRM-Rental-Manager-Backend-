"""Smart escrow holds — on-chain object id + release lifecycle."""
from sqlalchemy import Column, Integer, String, Numeric, Text, Enum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class EscrowStatus(str, enum.Enum):
    pending = "pending"
    funded = "funded"
    held = "held"
    released = "released"
    refunded = "refunded"
    cancelled = "cancelled"


class EscrowHold(Base):
    __tablename__ = "escrow_holds"

    id = Column(Integer, primary_key=True, index=True)
    lease_id = Column(Integer, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)

    amount_ugx = Column(Numeric(12, 2), nullable=False)
    amount_mist = Column(String(32), nullable=True)
    currency = Column(String(3), default="UGX", nullable=False)

    status = Column(Enum(EscrowStatus), default=EscrowStatus.pending, nullable=False)
    escrow_object_id = Column(String(128), nullable=True, index=True)
    fund_tx_digest = Column(String(128), nullable=True)
    release_tx_digest = Column(String(128), nullable=True)
    tenant_sui_address = Column(String(80), nullable=True)
    landlord_sui_address = Column(String(80), nullable=True)
    walrus_lease_blob_id = Column(String(256), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now(), server_default=func.now())
    funded_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)

    lease = relationship("Lease")
    tenant = relationship("Tenant")
