"""Landlord balance ledger — rent credits, platform fees, unit subscriptions, payouts."""
from __future__ import annotations

import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class LedgerEntryType(str, enum.Enum):
    rent_credit = "rent_credit"
    platform_fee = "platform_fee"
    unit_subscription = "unit_subscription"
    payout = "payout"
    adjustment = "adjustment"


class LandlordLedgerEntry(Base):
    __tablename__ = "landlord_ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True)

    entry_type = Column(Enum(LedgerEntryType), nullable=False, index=True)
    amount_ugx = Column(Numeric(14, 2), nullable=False)
    balance_after_ugx = Column(Numeric(14, 2), nullable=True)
    description = Column(String(500), nullable=True)
    reference = Column(String(120), nullable=True, index=True)
    period_month = Column(Integer, nullable=True)
    period_year = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=func.now(), server_default=func.now())

    owner = relationship("User", foreign_keys=[owner_id])
    payment = relationship("Payment", foreign_keys=[payment_id])
