"""On-chain payment receipts — anchors fiat (MoMo/Pesapal) and SUI wallet payments."""
from sqlalchemy import Column, Integer, String, Text, Enum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class ReceiptAnchorStatus(str, enum.Enum):
    pending = "pending"
    anchored = "anchored"
    failed = "failed"


class BlockchainReceipt(Base):
    __tablename__ = "blockchain_receipts"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=True, index=True)
    checkout_id = Column(Integer, ForeignKey("payment_checkouts.id", ondelete="SET NULL"), nullable=True, index=True)
    lease_id = Column(Integer, ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    network = Column(String(20), default="devnet", nullable=False)
    tx_digest = Column(String(128), nullable=True, index=True)
    receipt_hash = Column(String(128), nullable=True)
    walrus_blob_id = Column(String(256), nullable=True)
    object_id = Column(String(128), nullable=True)

    source = Column(String(32), nullable=False, default="sui")
    payment_method = Column(String(32), nullable=True)
    amount_ugx = Column(String(32), nullable=True)
    status = Column(Enum(ReceiptAnchorStatus), default=ReceiptAnchorStatus.pending, nullable=False)
    metadata_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now(), server_default=func.now())
    anchored_at = Column(DateTime, nullable=True)

    payment = relationship("Payment")
    checkout = relationship("PaymentCheckout")
