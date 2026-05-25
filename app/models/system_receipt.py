"""Enterprise system receipts — legal, tax, audit, and blockchain proof."""
from sqlalchemy import Column, Integer, String, Numeric, Text, Enum, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class ReceiptType(str, enum.Enum):
    rent_payment = "rent_payment"
    security_deposit = "security_deposit"
    commission = "commission"
    government_tax = "government_tax"
    blockchain = "blockchain"


class ReceiptStatus(str, enum.Enum):
    paid = "paid"
    pending = "pending"
    failed = "failed"
    escrowed = "escrowed"
    refunded = "refunded"


class SystemReceipt(Base):
    __tablename__ = "system_receipts"

    id = Column(Integer, primary_key=True, index=True)
    receipt_number = Column(String(64), unique=True, nullable=False, index=True)
    receipt_type = Column(Enum(ReceiptType), default=ReceiptType.rent_payment, nullable=False)
    status = Column(Enum(ReceiptStatus), default=ReceiptStatus.paid, nullable=False)

    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    escrow_id = Column(Integer, ForeignKey("escrow_holds.id", ondelete="SET NULL"), nullable=True, index=True)
    blockchain_receipt_id = Column(
        Integer, ForeignKey("blockchain_receipts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(8), default="UGX", nullable=False)
    payment_method = Column(String(32), nullable=True)
    transaction_reference = Column(String(128), nullable=True, index=True)

    tenant_name = Column(String(150), nullable=True)
    landlord_name = Column(String(150), nullable=True)
    property_name = Column(String(200), nullable=True)
    property_address = Column(String(500), nullable=True)
    unit_number = Column(String(50), nullable=True)
    lease_start = Column(String(32), nullable=True)
    lease_end = Column(String(32), nullable=True)
    period_label = Column(String(64), nullable=True)

    # Blockchain / Walrus
    wallet_address = Column(String(128), nullable=True)
    tx_hash = Column(String(128), nullable=True, index=True)
    contract_id = Column(String(128), nullable=True)
    walrus_blob_id = Column(String(256), nullable=True)
    explorer_url = Column(String(512), nullable=True)
    gas_fees_mist = Column(String(32), nullable=True)

    # Government tax (URA)
    tax_id = Column(String(64), nullable=True)
    ura_compliance_code = Column(String(64), nullable=True)
    vat_amount = Column(Numeric(12, 2), nullable=True)
    tax_percentage = Column(Numeric(5, 2), nullable=True)

    # Security
    verification_token = Column(String(64), unique=True, nullable=False, index=True)
    verification_hash = Column(String(128), nullable=False)
    checksum = Column(String(64), nullable=False)
    digital_signature = Column(String(128), nullable=False)

    pdf_path = Column(String(512), nullable=True)
    smart_summary = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)

    issued_at = Column(DateTime, default=func.now(), server_default=func.now(), nullable=False)
    emailed_at = Column(DateTime, nullable=True)
    is_void = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now(), server_default=func.now())

    payment = relationship("Payment")
    invoice = relationship("Invoice")
    tenant = relationship("Tenant")
    blockchain_receipt = relationship("BlockchainReceipt")
